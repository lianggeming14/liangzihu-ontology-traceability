"""Own only this deployment's HTTP/worker processes; never adopt databases."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import socket
from urllib.parse import urlsplit
from uuid import uuid4

import psutil
import httpx
from .config import contained_path

OWNER = "local-server/1"


class LifecycleError(RuntimeError):
    def __init__(self, code, message="本机运行时检查失败；请检查部署归属、端口与工具配置"):
        self.code = code
        super().__init__(message)


def _same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def _port_open(port):
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", int(port))) == 0


class NativeServices:
    """Explicit owned native services, or honest external-service mode.

    A deployment manifest is provisioned separately when creating/restoring an
    empty environment. A copied PID or a listening port never establishes
    ownership. Init/start do not initialize a pre-existing database cluster.
    """
    def __init__(self, config):
        self.config, self.runtime = config, config.runtime
        self.managed_pg = self.runtime.get("managed_postgres") is True
        self.managed_rdf = self.runtime.get("managed_fuseki") is True

    def validate(self):
        if not (self.managed_pg or self.managed_rdf):
            return
        deployment = load_state(self.config.data_dir / "deployment.json")
        if (not deployment or not deployment.get("deployment_id") or not _same_path(deployment.get("root", "."), self.config.root)
                or not _same_path(deployment.get("data_dir", "."), self.config.data_dir)
                or deployment.get("http_port") != self.config.port):
            raise LifecycleError("DEPLOYMENT_OWNERSHIP_REQUIRED", "部署清单与当前目录不符；换机后须验证并登记新的部署身份")
        self.deployment = deployment
        if self.managed_pg:
            self.pg_data = contained_path(self.config.data_dir, self.runtime["pg_data_dir"])
            self.pg_bin = (self.config.root / self.runtime["pg_bin"]).resolve()
            self.pg_port = int(self.runtime["pg_port"])
            if self.pg_port == 25449 or self.pg_port != deployment.get("pg_port") or not 1024 <= self.pg_port <= 65535:
                raise LifecycleError("POSTGRES_TARGET_REJECTED")
            from psycopg.conninfo import conninfo_to_dict
            for key, value in getattr(self.config,"sql",{}).items():
                if key.endswith("_dsn"):
                    target = conninfo_to_dict(value)
                    if target.get("host") not in ("127.0.0.1","localhost") or target.get("port") != str(self.pg_port):
                        raise LifecycleError("POSTGRES_CONNECTION_TARGET_MISMATCH", "数据库连接必须指向本部署受管端口，不能指回原集群")
            suffix = ".exe" if os.name == "nt" else ""
            self.pg_ctl = self.pg_bin / ("pg_ctl"+suffix)
            self.postgres = self.pg_bin / ("postgres"+suffix)
            if not self.pg_ctl.is_file() or not self.postgres.is_file() or not (self.pg_data / "PG_VERSION").is_file():
                raise LifecycleError("POSTGRES_NOT_PROVISIONED", "请先准备独立 PostgreSQL 17 数据目录与管理员/只读/导入账户，再运行 init")
        if self.managed_rdf:
            self.rdf_dir = contained_path(self.config.data_dir, self.runtime["fuseki_state_dir"])
            self.rdf_port = int(self.runtime["fuseki_port"])
            endpoint = urlsplit(self.config.fuseki_url)
            if self.rdf_port == 23049 or self.rdf_port != deployment.get("fuseki_port") or endpoint.hostname not in ("127.0.0.1", "localhost") or endpoint.port != self.rdf_port:
                raise LifecycleError("FUSEKI_TARGET_REJECTED")
            suffix = ".exe" if os.name == "nt" else ""
            self.java = (self.config.root / self.runtime["java_home"]).resolve() / "bin" / ("java"+suffix)
            self.jar = (self.config.root / self.runtime["fuseki_home"]).resolve() / "fuseki-server.jar"
            self.rdf_config = self.rdf_dir / "config.ttl"
            self.runner = self.config.root / "infra" / "local-server" / "LocalFusekiRunner.java"
            if not all(path.is_file() for path in (self.java, self.jar, self.rdf_config, self.runner)):
                raise LifecycleError("FUSEKI_NOT_PROVISIONED", "请配置 Java 21、Fuseki 6.2.0 与独立 TDB2 配置文件")
            if not self.rdf_config.resolve().is_relative_to(self.rdf_dir):
                raise LifecycleError("FUSEKI_CONFIG_REJECTED")
            from rdflib import Graph, URIRef
            graph = Graph().parse(self.rdf_config, format="turtle")
            locations = list(graph.objects(None, URIRef("http://jena.apache.org/2016/tdb#location")))
            if not locations:
                raise LifecycleError("FUSEKI_CONFIG_REJECTED")
            for location in locations:
                contained_path(self.rdf_dir, str(location))

    def _pg_identity(self):
        path = self.pg_data / "postmaster.pid"
        if not path.is_file():
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
        try:
            pid = int(lines[0])
            if not psutil.pid_exists(pid):
                return None
            actual = process_identity(pid)
            command = actual["command"]
            data_args = [command[index+1] for index, value in enumerate(command[:-1]) if value == "-D"]
            if (not _same_path(lines[1], self.pg_data) or int(lines[3]) != self.pg_port
                    or abs(actual["created"]-int(lines[2])) > 2 or not _same_path(actual["exe"], self.postgres)
                    or not data_args or not _same_path(data_args[-1], self.pg_data) or not _same_path(actual["cwd"], self.pg_data)):
                raise ValueError()
            return actual
        except (ValueError, IndexError, KeyError, OSError, psutil.Error):
            raise LifecycleError("POSTGRES_FOREIGN_PROCESS", "PostgreSQL 进程与数据目录归属不符；已拒绝接管") from None

    def _rdf_identity(self):
        saved = load_state(self.rdf_dir / "process.json")
        if not saved or not psutil.pid_exists(saved.get("pid", -1)):
            return None
        try:
            actual = process_identity(saved["pid"])
            # An exited runner's PID can be reused by an unrelated process.
            # A different creation time proves this is only a stale record;
            # do not adopt or signal the new process. start() still checks the
            # service port before launching a replacement runner.
            if abs(actual["created"]-float(saved["created"])) >= .01:
                return None
            command = actual["command"]
            if (saved.get("deployment_id") != self.deployment["deployment_id"]
                    or not _same_path(actual["exe"], self.java) or not _same_path(actual["cwd"], self.rdf_dir)):
                raise ValueError()
            # A legacy direct -jar launch may be inspected, but stop will not
            # pretend TerminateProcess is a graceful TDB2 shutdown.
            runner = str(self.runner) in command
            legacy = "-jar" in command and any(_same_path(value, self.jar) for value in command if value.endswith(".jar"))
            target = (str(self.rdf_config) in command and str(self.rdf_port) in command) if runner else ("--config="+str(self.rdf_config) in command and "--port="+str(self.rdf_port) in command)
            if not (runner or legacy) or not target:
                raise ValueError()
            return {**actual, "launch": "runner" if runner else "legacy"}
        except (ValueError, KeyError, OSError, psutil.Error):
            raise LifecycleError("FUSEKI_FOREIGN_PROCESS", "Fuseki 进程与部署身份不符；已拒绝接管") from None

    def status(self):
        if not (self.managed_pg or self.managed_rdf):
            return {"postgres": "external", "fuseki": "external"}
        self.validate()
        pg = self._pg_identity() if self.managed_pg else None
        rdf = self._rdf_identity() if self.managed_rdf else None
        return {"postgres": "running" if pg and _port_open(self.pg_port) else "stopped" if self.managed_pg else "external",
                "fuseki": ("running" if rdf.get("launch") == "runner" else "running-legacy-launch") if rdf and _port_open(self.rdf_port) else "stopped" if self.managed_rdf else "external"}

    def start(self):
        if not (self.managed_pg or self.managed_rdf):
            return self.status()
        self.validate()
        if self.managed_pg:
            identity = self._pg_identity()
            if not identity:
                if _port_open(self.pg_port):
                    raise LifecycleError("POSTGRES_PORT_IN_USE", "PostgreSQL 端口由其它进程占用")
                result = subprocess.run([str(self.pg_ctl), "-D", str(self.pg_data), "-w", "-t", "60", "-l", str(self.pg_data.parent/"server.log"), "start", "-o", f"-p {self.pg_port} -h 127.0.0.1"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=75, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                if result.returncode or not self._pg_identity():
                    raise LifecycleError("POSTGRES_START_FAILED", "PostgreSQL 启动失败；请检查本机私有运行日志")
        if self.managed_rdf:
            identity = self._rdf_identity()
            if not identity:
                if _port_open(self.rdf_port):
                    raise LifecycleError("FUSEKI_PORT_IN_USE", "Fuseki 端口由其它进程占用")
                stop_file = self.rdf_dir / "graceful-stop.request"
                stop_file.unlink(missing_ok=True)
                self.rdf_dir.mkdir(parents=True, exist_ok=True)
                # Runner has a local stop-file channel so Windows closes Jetty
                # and every TDB2 dataset through Java APIs rather than killing.
                command = [str(self.java), "-Xmx"+str(self.runtime.get("fuseki_heap", "1g")), "--class-path", str(self.jar), str(self.runner), str(self.rdf_config), str(self.rdf_port), str(stop_file), self.deployment["deployment_id"]]
                environment = {**os.environ, "FUSEKI_BASE": str(self.rdf_dir)}
                with (self.rdf_dir/"server.log").open("ab") as log:
                    process = subprocess.Popen(command, cwd=str(self.rdf_dir), env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, start_new_session=os.name != "nt")
                saved = {**process_identity(process.pid), "deployment_id": self.deployment["deployment_id"]}
                atomic_json(self.rdf_dir/"process.json", saved)
            timeout = time.monotonic()+60
            while time.monotonic() < timeout:
                if not self._rdf_identity():
                    raise LifecycleError("FUSEKI_START_FAILED", "Fuseki 启动失败；请检查本机私有运行日志")
                try:
                    with httpx.Client(timeout=2, trust_env=False) as client:
                        result = client.post(self.config.fuseki_url+"/query", data={"query": "ASK {}"}, headers={"Accept":"application/sparql-results+json"})
                        if result.status_code == 200 and result.json().get("boolean") is True:
                            break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(.3)
            else:
                raise LifecycleError("FUSEKI_READY_TIMEOUT", "Fuseki 在 60 秒内未就绪；请检查数据锁、配置与本机日志")
        return self.status()

    def stop(self):
        if not (self.managed_pg or self.managed_rdf):
            return
        self.validate()
        if self.managed_rdf:
            state_path = self.rdf_dir / "process.json"
            saved = load_state(state_path)
            identity = self._rdf_identity()
            if identity:
                if identity["launch"] != "runner":
                    raise LifecycleError("FUSEKI_LEGACY_STOP_REQUIRED", "现有 Fuseki 使用旧启动方式；请正常关闭后用本服务重新启动一次")
                (self.rdf_dir / "graceful-stop.request").write_text(self.deployment["deployment_id"], encoding="utf-8")
                deadline = time.monotonic()+60
                while time.monotonic() < deadline and owns_process(identity):
                    time.sleep(.2)
                if owns_process(identity):
                    raise LifecycleError("FUSEKI_STOP_TIMEOUT", "Fuseki 正常关闭超时；保留进程与数据，请检查本机日志")
            # Preserve a replacement runner's record if another controller
            # changed it while we waited for this runner to exit.
            if saved is not None and load_state(state_path) == saved:
                state_path.unlink(missing_ok=True)
        if self.managed_pg and self._pg_identity():
            result = subprocess.run([str(self.pg_ctl), "-D", str(self.pg_data), "-w", "-t", "60", "-m", "fast", "stop"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=75, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result.returncode or self._pg_identity():
                raise LifecycleError("POSTGRES_STOP_FAILED", "PostgreSQL 尚未停止；请检查本机日志")


def process_identity(pid):
    process = psutil.Process(int(pid))
    with process.oneshot():
        return {"pid": process.pid, "created": process.create_time(), "exe": str(Path(process.exe()).resolve()), "cwd": str(Path(process.cwd()).resolve()), "command": process.cmdline()}


def owns_process(identity):
    try:
        actual = process_identity(identity["pid"])
        return (abs(actual["created"] - float(identity["created"])) < 0.01
                and os.path.normcase(actual["exe"]) == os.path.normcase(identity["exe"])
                and os.path.normcase(actual["cwd"]) == os.path.normcase(identity["cwd"])
                and actual["command"] == identity["command"])
    except (psutil.Error, OSError, ValueError, KeyError, TypeError):
        return False


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + str(uuid4()) + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_state(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _state_path(config):
    return config.runtime_dir / "processes.json"


def _matches(config, state):
    return state and state.get("owner") == OWNER and state.get("config_path") == str(config.config_path)


def status(config):
    state = load_state(_state_path(config))
    valid = _matches(config, state)
    live = {name: bool(valid and state.get(name) and owns_process(state[name])) for name in ("supervisor", "http", "worker")}
    native = NativeServices(config).status()
    ready = all(value == "external" or value.startswith("running") for value in native.values())
    return {"status": "running" if all(live.values()) and ready else "degraded" if any(live.values()) else "stopped", "processes": live,
            "url": f"http://{config.host}:{config.port}/", "databases": native, "automatic_boot": "not-installed"}


def _command(config, operation):
    return [sys.executable, "-u", str(config.root / "scripts" / "run_local_server.py"), "--config", str(config.config_path), operation]


def _spawn(config, operation, **kwargs):
    options = {"cwd": str(config.root), "stdin": subprocess.DEVNULL, **kwargs}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    return subprocess.Popen(_command(config, operation), **options)


@contextmanager
def _start_lock(config):
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    path = config.runtime_dir / "start.lock"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        saved = load_state(path)
        if saved and not owns_process(saved):
            path.unlink()
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        else:
            raise RuntimeError("Another start operation is in progress") from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(process_identity(os.getpid()), stream)
        yield
    finally:
        path.unlink(missing_ok=True)


def start(config):
    with _start_lock(config):
        if (config.data_dir/"asset-placement.pending.json").exists():
            raise LifecycleError("ASSET_PLACEMENT_REQUIRED","恢复资产尚未对齐或校验失败；请先完成 place-restored-assets，保持服务停止")
        current = status(config)
        if current["status"] == "running":
            return {**current, "already_running": True}
        state = load_state(_state_path(config))
        if current["status"] == "degraded":
            raise RuntimeError("Stop the owned degraded deployment before starting")
        if state and not _matches(config, state):
            raise RuntimeError("Runtime directory belongs to another configuration")
        if _port_open(config.port):
            raise LifecycleError("HTTP_PORT_IN_USE", "控制台端口已由其它进程占用；拒绝启动重复服务")
        NativeServices(config).start()
        (config.runtime_dir / "stop-request.json").unlink(missing_ok=True)
        process = _spawn(config, "supervise", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(300):
            if process.poll() is not None:
                raise RuntimeError("Supervisor failed to start")
            current = status(config)
            if current["status"] == "running":
                try:
                    with httpx.Client(timeout=1, trust_env=False) as client:
                        response = client.get(f"http://127.0.0.1:{config.port}/health")
                        if response.status_code == 200 and response.json().get("service") == "local-ontology/1":
                            return current
                except (httpx.HTTPError, ValueError):
                    pass
            time.sleep(0.1)
        # A startup timeout must not leave an untracked supervisor behind.
        stop(config)
        raise RuntimeError("Supervisor startup timed out")


def _terminate(identity, timeout=15):
    if not owns_process(identity):
        return
    process = psutil.Process(identity["pid"])
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except psutil.TimeoutExpired:
        if owns_process(identity):
            process.kill(); process.wait(timeout=5)


def stop(config):
    state = load_state(_state_path(config))
    if not state:
        NativeServices(config).stop()
        return status(config)
    if not _matches(config, state):
        raise RuntimeError("Runtime directory belongs to another configuration")
    atomic_json(config.runtime_dir / "stop-request.json", {"deployment_id": state.get("deployment_id")})
    for _ in range(150):
        if not any(status(config)["processes"].values()):
            NativeServices(config).stop()
            return status(config)
        time.sleep(0.1)
    # Each stop is fenced by full OS identity; a recycled PID is left alone.
    for name in ("supervisor", "http", "worker"):
        identity = state.get(name)
        if identity:
            _terminate(identity)
    NativeServices(config).stop()
    return status(config)


def _pump(stream, logger):
    with stream:
        for line in iter(stream.readline, b""):
            # Children emit only structured safe messages. Drop any accidental
            # URL/credential-looking diagnostic rather than preserving secrets.
            value = line.decode("utf-8", errors="replace").strip()
            if any(token in value.lower() for token in ("postgresql://", "password", "bearer ", "token=", "dsn=")):
                value = "[redacted process diagnostic]"
            logger.info(value[:2000])


def supervise(config):
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    state = {"owner": OWNER, "deployment_id": str(uuid4()), "config_path": str(config.config_path), "supervisor": process_identity(os.getpid()), "services": {"sql": "external", "fuseki": "external"}}
    children, loggers, shutdown = {}, {}, threading.Event()
    for name in ("http", "worker"):
        logger = logging.getLogger("local-server-"+name)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = RotatingFileHandler(config.runtime_dir / (name+".log"), maxBytes=2*1024*1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        loggers[name] = logger
    def request_stop(*_): shutdown.set()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, request_stop)
    try:
        native = NativeServices(config)
        next_native_check = 0
        while not shutdown.is_set():
            request = load_state(config.runtime_dir / "stop-request.json")
            if request and request.get("deployment_id") == state["deployment_id"]:
                break
            if time.monotonic() >= next_native_check:
                try:
                    native.start()
                    state.pop("native_error", None)
                except LifecycleError as error:
                    state["native_error"] = error.code
                next_native_check = time.monotonic()+5
            changed = False
            for name, operation in (("http", "serve"), ("worker", "worker")):
                process = children.get(name)
                if process is None or process.poll() is not None:
                    if process is not None:
                        loggers[name].warning("process exited; restarting after cooldown")
                        shutdown.wait(2)
                        if shutdown.is_set():
                            break
                    process = _spawn(config, operation, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    children[name] = process
                    state[name] = process_identity(process.pid)
                    threading.Thread(target=_pump, args=(process.stdout, loggers[name]), daemon=True).start()
                    changed = True
            if changed:
                atomic_json(_state_path(config), state)
            shutdown.wait(0.5)
    finally:
        for name in ("worker", "http"):
            if state.get(name):
                _terminate(state[name])
        atomic_json(_state_path(config), {**state, "stopped": True})

from pathlib import Path
import base64, hashlib, json, subprocess, threading, time
from contextlib import contextmanager
from urllib.request import urlopen
from tempfile import TemporaryDirectory
import websocket
import imageio_ffmpeg

VER = "d96f7ebf-c709-4ec0-a598-13927ef2b54e"
CURRENT = "16c6ce16-e28c-5e9c-a766-874fca309c5f"
SHA = "a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def js(v):
    return json.dumps(v, ensure_ascii=False)


def clean_script(fn):
    return fn if len(fn) < 900 else fn[:900] + "..."


class CDP:
    def __init__(self, url):
        self.ws = websocket.create_connection(
            url, suppress_origin=True, timeout=20, enable_multithread=True
        )
        self.i = 0

    def call(self, method, params=None):
        self.i += 1
        self.ws.send(
            json.dumps({"id": self.i, "method": method, "params": params or {}})
        )
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def eval(self, expr):
        r = self.call(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in r:
            raise RuntimeError((clean_script(expr), r.get("result")))
        return r["result"].get("value")

    def wait(self, expr):
        end = time.monotonic() + 18
        while time.monotonic() < end:
            if self.eval(expr):
                return
            time.sleep(0.08)
        raise RuntimeError(
            (
                "DOM wait timed out",
                clean_script(expr),
                self.eval("document.body.innerText.slice(0,1000)"),
            )
        )

    def click(self, selector):
        self.wait(f"document.querySelector({js(selector)})!==null")
        xy = self.eval(
            f"""(()=>{{let e=document.querySelector({js(selector)});e.scrollIntoView({{block:'center',behavior:'instant'}});let r=e.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}})()"""
        )
        x, y = xy
        for event in ("mouseMoved", "mousePressed", "mouseReleased"):
            q = {"type": event, "x": x, "y": y}
            if event != "mouseMoved":
                q.update(button="left", clickCount=1)
            self.call("Input.dispatchMouseEvent", q)

    def scroll_to(self, expr, offset=160):
        self.eval(
            f"(()=>{{const e={expr};if(!e)throw Error('scroll target not found'); window.scrollBy({{top:e.getBoundingClientRect().top-{offset},behavior:'instant'}})}})()"
        )

    def png(self, path):
        time.sleep(0.28)
        path.write_bytes(
            base64.b64decode(
                self.call(
                    "Page.captureScreenshot", {"format": "png", "fromSurface": True}
                )["data"]
            )
        )


class Recording:
    def __init__(self, wsurl, path):
        self.url, self.path = wsurl, path
        self.stop = threading.Event()
        self.rows = []

    def start(self):
        self.temp = TemporaryDirectory()
        self.thread = threading.Thread(target=self.capture, daemon=True)
        self.thread.start()
        time.sleep(0.7)

    def capture(self):
        ws = CDP(self.url)
        try:
            while not self.stop.is_set():
                started = time.monotonic()
                r = ws.call(
                    "Page.captureScreenshot",
                    {"format": "jpeg", "quality": 78, "fromSurface": True},
                )
                p = Path(self.temp.name) / (f"f{len(self.rows):04}.jpg")
                p.write_bytes(base64.b64decode(r["data"]))
                self.rows.append((started, p))
                self.stop.wait(max(0, 0.16 - (time.monotonic() - started)))
        finally:
            ws.ws.close()

    def finish(self):
        time.sleep(0.8)
        self.stop.set()
        self.thread.join(20)
        end = time.monotonic()
        assert len(self.rows) > 4
        manifest = Path(self.temp.name) / "timing.txt"
        rows = ["ffconcat version 1.0"]
        for i, (t, p) in enumerate(self.rows):
            dt = self.rows[i + 1][0] - t if i + 1 < len(self.rows) else end - t
            rows.extend([f"file '{p.name}'", f"duration {dt:.5f}"])
        rows.append(f"file '{self.rows[-1][1].name}'")
        manifest.write_text("\n".join(rows) + "\n", encoding="ascii")
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(manifest),
                "-vf",
                "fps=25,scale=1920:1080",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "17",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(self.path),
            ],
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.temp.cleanup()
        return {
            "file": self.path.name,
            "sampled_frames": len(self.rows),
            "recording_seconds": round(end - self.rows[0][0], 3),
            "sha256": sha(self.path),
        }


@contextmanager
def open_browser(executable, scratch):
    """Use a temporary, self-owned browser profile and a loopback debugger."""
    profile = scratch / "chrome-profile"
    process = subprocess.Popen(
        [
            str(executable),
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-sync",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            "--user-data-dir=" + str(profile),
            "about:blank",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tab = None
    try:
        deadline = time.monotonic() + 20
        portfile = profile / "DevToolsActivePort"
        while not portfile.is_file():
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Chromium failed to open its local debugging socket")
            time.sleep(0.06)
        port = portfile.read_text().splitlines()[0]
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as response:
            tabs = json.load(response)
        url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
        tab = CDP(url)
        tab.call("Page.enable")
        tab.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 810, "deviceScaleFactor": 1.5, "mobile": False},
        )
        yield tab, url
    finally:
        if tab:
            try:
                tab.call("Browser.close")
            except websocket.WebSocketException:
                pass
            tab.ws.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)

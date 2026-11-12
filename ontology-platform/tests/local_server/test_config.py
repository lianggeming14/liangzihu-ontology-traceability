"""Configuration safety tests; all paths and credentials here are synthetic."""
import json
import os
from pathlib import Path

import pytest

from local_server.config import Config, ConfigError


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    root = tmp_path / "source"
    (root / "config").mkdir(parents=True)
    (root / "config" / "mapping.json").write_text("{}", encoding="utf-8")
    payload = {
        "root": str(root), "data_dir": "data", "review_dir": "review",
        "mapping_file": "config/mapping.json",
        "sql": {
            "admin_dsn_env": "CONFIG_TEST_ADMIN_DSN",
            "api_dsn_env": "CONFIG_TEST_API_DSN",
            "worker_dsn_env": "CONFIG_TEST_WORKER_DSN",
            "allowed_targets": [{"host": "127.0.0.1", "port": 25459, "database": "lzo_local_test"}],
        },
        "fuseki_url": "http://127.0.0.1:23059/fish_l1",
        "fuseki_allowed_targets": ["http://127.0.0.1:23059/fish_l1"],
    }
    for role in ("ADMIN", "API", "WORKER"):
        monkeypatch.setenv("CONFIG_TEST_" + role + "_DSN", "postgresql://test:private-password@127.0.0.1:25459/lzo_local_test")
    path = tmp_path / "private.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload


def save(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize("host",["::1","::","[::1]"])
def test_ipv6_bind_is_explicitly_rejected_in_this_ipv4_release(config_file,host):
    path,payload=config_file
    payload.update(host=host,allow_remote_bind=True)
    save(path,payload)
    with pytest.raises(ConfigError,match="IPv6"):
        Config.load(path)


def test_load_resolves_source_and_data_separately_without_revealing_secrets(config_file):
    path, payload = config_file
    config = Config.load(path)
    assert config.root == Path(payload["root"])
    assert config.data_dir == path.parent / "data"
    assert config.mapping_file == config.root / "config/mapping.json"
    assert config.runtime_dir == config.data_dir / "runtime"
    assert config.host == "127.0.0.1"
    assert config.limits["upload_bytes"] == 64 * 1024 * 1024
    assert "private-password" not in repr(config)
    assert "postgresql://" not in repr(config)


@pytest.mark.parametrize("change", ["sql_target", "fuseki_target", "remote_host", "missing_allowlist", "invalid_limit", "source_mapping_escape", "data_owns_source"])
def test_rejects_unsafe_or_ambiguous_configuration(config_file, change):
    path, payload = config_file
    if change == "sql_target":
        payload["sql"]["allowed_targets"][0]["port"] = 25449
    elif change == "fuseki_target":
        payload["fuseki_url"] = "http://127.0.0.1:23049/fish_l1"
    elif change == "remote_host":
        payload["host"] = "0.0.0.0"
    elif change == "missing_allowlist":
        del payload["sql"]["allowed_targets"]
    elif change == "invalid_limit":
        payload["limits"] = {"upload_bytes": 0}
    elif change == "source_mapping_escape":
        payload["mapping_file"] = "../secret.json"
    else:
        payload["data_dir"] = str(path.parent)
    save(path, payload)
    with pytest.raises(ConfigError) as failure:
        Config.load(path)
    assert "private-password" not in str(failure.value)


def test_explicit_container_dns_targets_are_supported(config_file, monkeypatch):
    path, payload = config_file
    for role in ("ADMIN", "API", "WORKER"):
        monkeypatch.setenv("CONFIG_TEST_" + role + "_DSN", "host=postgres port=5432 dbname=lzo_local_test user=test password=private-password")
    payload["sql"]["allowed_targets"] = [{"host": "postgres", "port": 5432, "database": "lzo_local_test"}]
    payload["fuseki_url"] = "http://fuseki:3030/fish_l1"
    payload["fuseki_allowed_targets"] = [payload["fuseki_url"]]
    save(path, payload)
    assert Config.load(path).fuseki_url == "http://fuseki:3030/fish_l1"


def test_data_paths_cannot_escape_through_traversal_or_symlink(config_file, tmp_path):
    path, _ = config_file
    config = Config.load(path)
    with pytest.raises(ConfigError):
        config.data_path("..", "secret")
    config.data_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (config.data_dir / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("OS denied creating a synthetic directory symlink")
    with pytest.raises(ConfigError):
        config.data_path("link", "secret")


def test_invalid_dsn_does_not_echo_credentials(config_file, monkeypatch):
    path, _ = config_file
    monkeypatch.setenv("CONFIG_TEST_API_DSN", "postgresql://test:private-password@127.0.0.1:bad/db")
    with pytest.raises(ConfigError) as failure:
        Config.load(path)
    assert "private-password" not in str(failure.value)


@pytest.mark.parametrize("key,value", [("mapping_file", None), ("mapping_file", 123), ("runtime", {"directory": "../outside"}), ("runtime", {"directory": None})])
def test_invalid_path_shapes_raise_sanitized_configuration_errors(config_file, key, value):
    path, payload = config_file
    payload[key] = value
    save(path, payload)
    with pytest.raises(ConfigError):
        Config.load(path)


def test_backup_options_cannot_leak_credentials_in_config_repr(config_file):
    path, payload = config_file
    payload["backup"] = {"source_options": {"dsn": "postgresql://fake:private-backup-password@localhost:5432/fake"}}
    save(path, payload)
    assert "private-backup-password" not in repr(Config.load(path))

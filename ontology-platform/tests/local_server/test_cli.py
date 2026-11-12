import json
from types import SimpleNamespace
from pathlib import Path
import pytest

from local_server.cli import build_parser, main


def test_cli_has_one_configuration_entry_for_all_operations():
    parser = build_parser()
    for operation in ("init", "start", "stop", "restart", "status", "serve", "worker", "open"):
        args = parser.parse_args(["--config", "private.json", operation])
        assert args.config == "private.json"
        assert args.command == operation
    assert parser.parse_args(["--config", "x", "verify-backup", "manifest.json"]).manifest == "manifest.json"
    assert parser.parse_args(["--config", "x", "retry-job", "test-job"]).job_id == "test-job"
    assert parser.parse_args(["--config","x","place-restored-assets","manifest.json","--options","restore.json"]).options=="restore.json"


def test_cli_configuration_error_does_not_echo_private_content(capsys):
    assert main(["--config", "nonexistent-private.json", "status"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "COMMAND_FAILED"
    assert "nonexistent-private" not in json.dumps(result)


def test_failed_restore_keeps_service_start_blocked(tmp_path,monkeypatch,capsys):
    from local_server import cli,backup
    config=SimpleNamespace(root=tmp_path,data_dir=tmp_path,runtime_dir=tmp_path/"runtime",runtime={},
                           config_path=tmp_path/"config.json",host="127.0.0.1",port=8792)
    options=tmp_path/"options.json";options.write_text('{"asset_destination":"staging"}')
    monkeypatch.setattr(cli,"load_config",lambda *args:config)
    def rejected(*args,**kwargs):raise backup.BackupError("RESTORE_SQL_FULL_READBACK_MISMATCH")
    monkeypatch.setattr(backup,"restore_backup",rejected)
    assert cli.main(["--config","ignored","restore","manifest.json","--options",str(options)])==1
    assert (tmp_path/"asset-placement.pending.json").is_file()
    assert json.loads(capsys.readouterr().out)["error"]["code"]=="RESTORE_SQL_FULL_READBACK_MISMATCH"


@pytest.mark.parametrize("command",["serve","worker","supervise"])
def test_pending_assets_also_block_foreground_services(tmp_path,monkeypatch,capsys,command):
    from local_server import cli,http,worker,lifecycle
    config=SimpleNamespace(data_dir=tmp_path)
    (tmp_path/"asset-placement.pending.json").write_text('{}')
    monkeypatch.setattr(cli,"load_config",lambda *args:config)
    def forbidden(*args,**kwargs):pytest.fail("pending restoration must not start a foreground service")
    monkeypatch.setattr(http,"serve",forbidden)
    monkeypatch.setattr(worker,"run_worker",forbidden)
    monkeypatch.setattr(lifecycle,"supervise",forbidden)
    assert cli.main(["--config","ignored",command])==1
    assert json.loads(capsys.readouterr().out)["error"]["code"]=="ASSET_PLACEMENT_REQUIRED"


def test_pending_assets_cannot_publish_a_bootstrap_release(tmp_path,monkeypatch,capsys):
    from local_server import cli
    (tmp_path/"asset-placement.pending.json").write_text('{}')
    monkeypatch.setattr(cli,"load_config",lambda *args:SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(cli,"bootstrap_release",lambda *args,**kwargs:pytest.fail("pending assets cannot publish"))
    assert cli.main(["--config","ignored","bootstrap-release","--proof","ignored-proof"])==1
    assert json.loads(capsys.readouterr().out)["error"]["code"]=="ASSET_PLACEMENT_REQUIRED"

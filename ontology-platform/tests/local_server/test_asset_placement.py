"""Synthetic verified-restore proof; real filesystem placement, no SQL claim."""
import hashlib
import errno
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_server.backup import BackupError, place_restored_assets
from local_server.config import contained_path
from local_server.query import QueryService


@pytest.fixture
def restored(tmp_path):
    root=tmp_path/"new-machine"/"source"
    data=root/"private-data"
    data.mkdir(parents=True)
    (data/"deployment.json").write_text('{"deployment_id":"NEW-IDENTITY"}',encoding="utf8")
    stage=data/"restored-assets"
    stage.mkdir()
    manifest={"contract":"local-server-navigation/1","namespace":"urn:test:","root_iri":"urn:test:root",
              "concepts":[{"iri":"urn:test:class:ponds","parent_iri":"urn:test:root","label":"池塘"}]}
    contents={"uploads/u/ponds.csv":b"id,name\n1,pond\n",
              "imports/job/public/manifest.json":json.dumps(manifest).encode(),
              "releases/r/vocabulary.ttl":b"<urn:s> <urn:p> <urn:o> .\n",
              "cad-imports/batch/input/bundle.json":b'{"contract":"lzo-cad-batch/1","synthetic":true}',
              "cad-imports/batch/input/source-files/original.bin":b'\x00retained-source\xff',
              "mapping/mapping.json":b'{"version":"1"}'}
    assets=[]
    for name,payload in contents.items():
        target=stage/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(payload)
        label,relative=name.split("/",1)
        assets.append({"label":label,"relative_path":relative,"raw_size_bytes":len(payload),"raw_sha256":hashlib.sha256(payload).hexdigest()})
    saved={"format":"local-server-portable-backup-v1","status":"complete","backup_id":"synthetic-backup",
           "databases":{"main":{"inventory":{"tables":[{"name":"jobs"}],"schemas":["lzo_local"]}}},
           "rdf":{"inventory":{"quad_count":1,"named_graphs":[{"graph":"urn:test:graph"}]}},"assets":assets}
    backup=tmp_path/"backup"
    backup.mkdir()
    path=backup/"manifest.json"
    path.write_text(json.dumps(saved),encoding="utf8")
    (backup/"manifest.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest(),encoding="ascii")
    report={"status":"restored_verified","backup_id":"synthetic-backup","deployment_id":"restore-run",
            "rdf":saved["rdf"]["inventory"],"databases":{"main":{"status":"full_readback_verified","table_count":1,"schemas":["lzo_local"]}},"asset_count":len(assets)}
    (stage/"restore-report.json").write_text(json.dumps(report),encoding="utf8")
    config=SimpleNamespace(root=root,data_dir=data,review_dir=root/"review",runtime_dir=data/"runtime",runtime={},
                           fuseki_url="http://127.0.0.1:23059/fish_l1",limits={"query_timeout_seconds":1,"page_size":10,"max_page_size":100})
    config.data_path=lambda *parts:contained_path(data,*parts)
    options={"asset_destination":str(stage),"asset_placement":{
        "uploads":{"base":"data","path":"uploads"},"imports":{"base":"data","path":"imports"},
        "releases":{"base":"data","path":"releases"},"cad-imports":{"base":"data","path":"cad-imports"},
        "mapping":{"base":"data","path":"restored-mapping"}}}
    return config,path,options,saved


def test_placed_assets_make_persisted_job_and_release_references_readable_under_new_root(restored):
    config,path,options,_=restored
    identity=(config.data_dir/"deployment.json").read_bytes()
    result=place_restored_assets(config,path,target_options=options)
    assert result["status"]=="assets_placed_verified"
    job={"source_path":"uploads/u/ponds.csv"}
    assert config.data_path(job["source_path"]).read_bytes()==b"id,name\n1,pond\n"
    release={"release_id":"r","path_base":"data","manifest_path":"imports/job/public/manifest.json",
             "navigation_dir":"imports/job/public","namespace":"urn:test:","rdf_graph":"urn:test:graph"}
    assert QueryService(config,release).children("urn:test:root")["items"][0]["label"]=="池塘"
    assert (config.data_dir/"restored-mapping"/"mapping.json").is_file()
    assert (Path(options["asset_destination"])/"uploads/u/ponds.csv").is_file()
    assert (config.data_dir/"deployment.json").read_bytes()==identity
    assert not (config.data_dir/"asset-placement.pending.json").exists()


def test_conflicting_nonempty_target_refuses_all_placement_and_blocks_start(restored):
    config,path,options,_=restored
    target=config.data_dir/"imports"
    target.mkdir()
    (target/"keep.txt").write_text("keep",encoding="utf8")
    with pytest.raises(BackupError,match="CONFLICT|NOT_EMPTY"):
        place_restored_assets(config,path,target_options=options)
    assert not (config.data_dir/"uploads").exists()
    assert (target/"keep.txt").read_text()=="keep"
    assert (config.data_dir/"asset-placement.pending.json").is_file()


@pytest.mark.parametrize("change",["unverified","missing_mapping","escape","native_target","identity_file","changed_asset"])
def test_unverified_unsafe_or_changed_assets_are_refused(restored,change):
    config,path,options,saved=restored
    stage=Path(options["asset_destination"])
    if change=="unverified":
        report=json.loads((stage/"restore-report.json").read_text())
        report["status"]="failed"
        (stage/"restore-report.json").write_text(json.dumps(report))
    elif change=="missing_mapping":options["asset_placement"].pop("mapping")
    elif change=="escape":options["asset_placement"]["mapping"]["path"]="../outside"
    elif change=="native_target":options["asset_placement"]["mapping"]={"base":"data","path":"postgres/data"}
    elif change=="identity_file":
        saved["assets"][0]["relative_path"]="deployment.json"
        path.write_text(json.dumps(saved))
        (path.parent/"manifest.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest())
    else:(stage/"uploads/u/ponds.csv").write_bytes(b"CHANGED")
    with pytest.raises(BackupError):place_restored_assets(config,path,target_options=options)
    assert not (config.data_dir/"uploads").exists()


def test_symlink_in_a_declared_asset_subtree_is_rejected(restored):
    config,path,options,_=restored
    stage=Path(options["asset_destination"])
    original=stage/"uploads/u/ponds.csv"
    original.rename(original.with_suffix(".actual"))
    try:original.symlink_to(original.with_suffix(".actual"))
    except OSError:pytest.skip("OS denied creating a synthetic symlink")
    with pytest.raises(BackupError,match="LINK|PATH"):
        place_restored_assets(config,path,target_options=options)


def test_configured_roots_can_be_on_different_filesystems(restored,monkeypatch):
    config,path,options,_=restored
    options["asset_placement"]["mapping"]={"base":"root","path":"restored-mapping"}
    rename=Path.rename
    def different_devices(source,target):
        # Emulate data_dir mounted on another volume from the source root.
        if source.resolve().is_relative_to(config.data_dir) != Path(target).resolve().is_relative_to(config.data_dir):
            raise OSError(errno.EXDEV,"synthetic cross-device boundary")
        return rename(source,target)
    monkeypatch.setattr(Path,"rename",different_devices)
    result=place_restored_assets(config,path,target_options=options)
    assert result["status"]=="assets_placed_verified"
    assert (config.root/"restored-mapping/mapping.json").read_bytes()==b'{"version":"1"}'


def test_roots_without_manifest_assets_are_not_implicitly_added(restored):
    config,path,options,saved=restored
    stage=Path(options["asset_destination"])
    (stage/"releases/r/vocabulary.ttl").unlink()
    (stage/"releases/r").rmdir();(stage/"releases").rmdir()
    saved["assets"]=[record for record in saved["assets"] if record["label"]!="releases"]
    path.write_text(json.dumps(saved))
    (path.parent/"manifest.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest())
    report=json.loads((stage/"restore-report.json").read_text())
    report["asset_count"]=len(saved["assets"])
    (stage/"restore-report.json").write_text(json.dumps(report))
    with pytest.raises(BackupError,match="EXPLICIT_COMPLETE_ASSET_PLACEMENT_REQUIRED"):
        place_restored_assets(config,path,target_options=options)
    assert not (config.data_dir/"releases").exists()


@pytest.mark.parametrize("mapping",[
    {"base":"root","path":"cad-imports"},
    {"base":"review","path":"cad-imports"},
    {"base":"data","path":"moved-cad"},
    {"base":"data","path":"archive/cad-imports"},
])
def test_cad_source_reference_rejects_changed_base_or_path_before_any_placement(restored,mapping):
    config,path,options,_=restored
    options["asset_placement"]["cad-imports"]=mapping
    with pytest.raises(BackupError,match="BUSINESS_REFERENCE_ROOT_MUST_RETAIN_ITS_LABEL"):
        place_restored_assets(config,path,target_options=options)
    for label in ("uploads","imports","releases","cad-imports"):
        assert not (config.data_dir/label).exists()
    assert not (config.root/"cad-imports").exists()
    assert not (config.review_dir/"cad-imports").exists()
    assert not (config.data_dir/"moved-cad").exists()
    assert not (config.data_dir/"archive").exists()


def test_cad_sources_restore_at_persisted_relative_path_with_verified_hashes(restored):
    config,path,options,saved=restored
    result=place_restored_assets(config,path,target_options=options)
    assert result["status"]=="assets_placed_verified"
    assert result["labels"]["cad-imports"]=={"base":"data","path":"cad-imports"}
    release={"cad_source_path":"cad-imports/batch/input/bundle.json"}
    bundle=config.data_path(release["cad_source_path"])
    assert bundle.read_bytes()==b'{"contract":"lzo-cad-batch/1","synthetic":true}'
    assert (bundle.parent/"source-files/original.bin").read_bytes()==b'\x00retained-source\xff'
    for record in saved["assets"]:
        if record["label"]=="cad-imports":
            raw=config.data_path("cad-imports",record["relative_path"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==record["raw_sha256"]
            assert len(raw)==record["raw_size_bytes"]
    assert result["services_started"] is False and result["release_published"] is False


def test_changed_cad_source_hash_is_rejected_before_placement(restored):
    config,path,options,_=restored
    source=Path(options["asset_destination"])/"cad-imports/batch/input/source-files/original.bin"
    original=source.read_bytes()
    source.write_bytes(original[:-1]+b'\x00')
    assert source.stat().st_size==len(original)
    with pytest.raises(BackupError,match="RESTORED_ASSET_HASH_OR_SIZE_MISMATCH"):
        place_restored_assets(config,path,target_options=options)
    assert not (config.data_dir/"cad-imports").exists()
    assert not (config.data_dir/"uploads").exists()

"""从 B3 交付目录打包、核对成员和 SHA-256，生成可单独验证的 ZIP。"""
import hashlib
import io
from pathlib import Path
import re
import sys
from zipfile import ZipFile, ZIP_DEFLATED, is_zipfile

folder = Path(__file__).resolve().parents[2]
repo = folder.parents[1]
sys.path.insert(0, str(repo / "tools"))
from restore_github_snapshot import checked_path, forbidden_reason, scan_secrets

index = folder / "文件校验清单.sha256"
archive = folder.parent / "武昌鱼项目_B3申报补充材料.zip"

def sha(data):
    return hashlib.sha256(data).hexdigest()

def inspect(name, data):
    checked_path(name)
    if forbidden_reason(name) or Path(name).name.startswith("~$"):
        raise ValueError(f"文件需排除：{name}")
    scan_secrets(data, name)
    if re.search(rb'(?i)["\']app_secret["\']\s*:\s*["\'][A-Za-z0-9_-]{12,}', data):
        raise ValueError(f"检测到身份验证字段：{name}")
    if is_zipfile(io.BytesIO(data)):
        with ZipFile(io.BytesIO(data)) as inner:
            for entry in inner.infolist():
                if not entry.is_dir():
                    inspect(entry.filename, inner.read(entry))

members = {}
for f in sorted(x for x in folder.rglob("*") if x.is_file() and x != index):
    rel = f.relative_to(folder).as_posix()
    data = f.read_bytes()
    inspect(rel, data)
    members[rel] = sha(data)

index.write_bytes("".join(f"{v}  {k}\n" for k,v in members.items()).encode("utf-8"))
members[index.name] = sha(index.read_bytes())
with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=8) as z:
    for name in members:
        z.write(folder / name, name)
with ZipFile(archive) as z:
    assert z.testzip() is None
    assert set(z.namelist()) == set(members)
    for name, expected in members.items():
        assert sha(z.read(name)) == expected, name
print(f"{len(members)} files, {archive.stat().st_size} bytes, SHA-256 {sha(archive.read_bytes())}")

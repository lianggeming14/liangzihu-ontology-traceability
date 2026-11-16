"""Download and byte-verify only the pinned, reviewed public CAD sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


def download_sources(manifest_path: Path, destination: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repository = manifest["repository"]
    if repository != "litt1eloser/liangzihu-farm-platform":
        raise ValueError("Unexpected source repository")
    destination = destination.resolve()
    reports = []
    for spec in manifest["source_files"]:
        path = PurePosixPath(spec["path"])
        if path.is_absolute() or any(p in ("", ".", "..") for p in path.parts) or "\\" in spec["path"]:
            raise ValueError("Unsafe source path")
        if not re.fullmatch(r"[a-f0-9]{40}", spec["commit"]):
            raise ValueError("Source must be a fixed commit")
        target = (destination / path).resolve()
        if not target.is_relative_to(destination):
            raise ValueError("Source escapes destination")
        if target.exists():
            data = target.read_bytes()
        else:
            url = "https://raw.githubusercontent.com/" + repository + "/" + spec["commit"] + "/" + quote(path.as_posix(), safe="/")
            for attempt in range(3):
                try:
                    with urlopen(Request(url, headers={"User-Agent": "lzo-pinned-source-import/1"}), timeout=45) as response:
                        data = response.read(spec["size_bytes"] + 1)
                    break
                except OSError:
                    if attempt == 2:
                        raise
                    time.sleep(1)
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != spec["git_blob_sha"] or len(data) != spec["size_bytes"]:
            raise ValueError("Pinned source content mismatch: " + spec["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        reports.append({**spec, "sha256": hashlib.sha256(data).hexdigest(), "verified": True})
        print(json.dumps({"verified": spec["path"], "bytes": len(data)}, ensure_ascii=True), flush=True)
    (destination.parent / "download-verification.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    reports = download_sources(args.manifest, args.destination)
    print(json.dumps({"files": len(reports), "bytes": sum(r["size_bytes"] for r in reports), "all_verified": True}))

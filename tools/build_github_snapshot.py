#!/usr/bin/env python3
"""Build bounded ZIP volumes from staged or explicitly selected working-tree files."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
import zlib

from restore_github_snapshot import (
    ARCHIVE_LIMIT, FILE_COUNT_LIMIT, FILE_LIMIT, FORMAT, MANIFEST_LIMIT, TOTAL_LIMIT,
    SnapshotError, checked_path, digest, forbidden_reason, no_symlink_chain,
    scan_secrets, transport_reason,
)


def find_git(explicit: str | None = None) -> str:
    candidates = [explicit] if explicit else [
        shutil.which("git"),
        "C:/Users/robot/.conda/envs/direct/Library/bin/git.exe",
        "C:/Program Files/Git/cmd/git.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise SnapshotError("Git executable not found; supply --git PATH")


def git_call(git: str, root: Path, *args: str, allowed=(0,)) -> subprocess.CompletedProcess:
    result = subprocess.run([git, "-c", f"safe.directory={root.as_posix()}",
                             "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode not in allowed:
        raise SnapshotError(f"Git operation failed ({args[0]}, exit {result.returncode})")
    return result


def index_listing(git: str, root: Path) -> tuple[bytes, list[str]]:
    raw = git_call(git, root, "ls-files", "--cached", "--stage", "-z").stdout
    paths = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        try:
            prefix, filename = entry.split(b"\t", 1)
            mode, _object_id, stage = prefix.decode("ascii").split()
            name = filename.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise SnapshotError("invalid Git index listing") from exc
        if stage != "0":
            raise SnapshotError(f"unmerged Git index entry: {name}")
        if mode not in ("100644", "100755"):
            raise SnapshotError(f"symlink, submodule, or nonregular index entry: {name}")
        paths.append(checked_path(name))
    if len(paths) != len(set(paths)) or len(paths) != len({p.casefold() for p in paths}):
        raise SnapshotError("duplicate or case-colliding index paths")
    if not paths:
        raise SnapshotError("Git index is empty; run git add before building")
    return raw, paths


def working_tree_listing(git: str, root: Path) -> tuple[bytes, list[str]]:
    """Read tracked plus non-ignored untracked paths without refreshing/writing the index."""
    raw = git_call(git, root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout
    try:
        paths = [checked_path(entry.decode("utf-8")) for entry in raw.split(b"\0") if entry]
    except UnicodeError as exc:
        raise SnapshotError("invalid working-tree path encoding") from exc
    if len(paths) != len(set(paths)) or len(paths) != len({p.casefold() for p in paths}):
        raise SnapshotError("duplicate or case-colliding working-tree paths")
    if not paths:
        raise SnapshotError("working-tree file selection is empty")
    return raw, paths


def stable_read(root: Path, name: str) -> tuple[bytes, tuple]:
    target = root.joinpath(*name.split("/"))
    no_symlink_chain(root, target)
    try:
        before = target.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > FILE_LIMIT:
            raise SnapshotError(f"nonregular or oversized file: {name}")
        with target.open("rb") as stream:
            data = stream.read(FILE_LIMIT + 1)
            after = os.fstat(stream.fileno())
    except FileNotFoundError as exc:
        raise SnapshotError(f"selected working-tree file is missing: {name}") from exc
    sig = lambda s: (s.st_size, s.st_mtime_ns, s.st_ino)
    if len(data) > FILE_LIMIT or len(data) != before.st_size or sig(before) != sig(after):
        raise SnapshotError(f"file changed while reading: {name}")
    return data, (*sig(after), digest(data))


def assert_stable(git: str, root: Path, index: bytes, fingerprints: dict,
                  working_tree: bool = False) -> None:
    listing = working_tree_listing if working_tree else index_listing
    if listing(git, root)[0] != index:
        label = "working-tree file list" if working_tree else "Git index"
        raise SnapshotError(f"{label} changed during snapshot inspection")
    if not working_tree and git_call(
            git, root, "diff", "--quiet", "--no-ext-diff", "--ignore-submodules",
            allowed=(0, 1)).returncode:
        raise SnapshotError("tracked working-tree changes are not staged; run git add and retry")
    for name, expected in fingerprints.items():
        if stable_read(root, name)[1] != expected:
            raise SnapshotError(f"working-tree file changed during snapshot inspection: {name}")


def collect(root: Path, git: str, working_tree: bool = False) -> tuple[list[tuple[str, bytes]], list[dict], bytes, dict]:
    actual_root = git_call(git, root, "rev-parse", "--show-toplevel").stdout.decode("utf-8").strip()
    if Path(actual_root).resolve() != root.resolve():
        raise SnapshotError("--root must identify the Git repository root")
    listing = working_tree_listing if working_tree else index_listing
    index, names = listing(git, root)
    if not working_tree and git_call(git, root, "diff", "--quiet", "--no-ext-diff", "--ignore-submodules",
                allowed=(0, 1)).returncode:
        raise SnapshotError("tracked working-tree changes are not staged; run git add and retry")
    payloads, excluded, fingerprints, total = [], [], {}, 0
    for name in sorted(names):
        reason = forbidden_reason(name)
        if reason:
            # Refuse instead of quietly skipping: --check-only also gates normal git push.
            label = "selected working-tree" if working_tree else "indexed"
            raise SnapshotError(f"prohibited {label} file ({reason}); path only: {name}")
        data, fingerprint = stable_read(root, name)
        scan_secrets(data, name)  # Includes separately transported workflows.
        fingerprints[name] = fingerprint
        excluded_reason = transport_reason(name)
        if excluded_reason:
            excluded.append({"path": name, "reason": excluded_reason})
            continue
        payloads.append((name, data))
        total += len(data)
        if len(payloads) > FILE_COUNT_LIMIT or total > TOTAL_LIMIT:
            raise SnapshotError("snapshot exceeds 2000 files or 150 MiB expanded budget")
    if not payloads:
        raise SnapshotError("no project files remain after transport exclusions")
    assert_stable(git, root, index, fingerprints, working_tree)
    return payloads, excluded, index, fingerprints


def compressed_entry_size(name: str, data: bytes) -> int:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = compressor.compress(data) + compressor.flush()
    # Local file header + central-directory header + both UTF-8 filenames.
    return len(packed) + 30 + 46 + 2 * len(name.encode("utf-8"))


def groups_for(payloads: list[tuple[str, bytes]]) -> list[list[tuple[str, bytes]]]:
    groups, current, size = [], [], 22  # End-of-central-directory record.
    for name, data in payloads:
        contribution = compressed_entry_size(name, data)
        if contribution + 22 > ARCHIVE_LIMIT:
            raise SnapshotError(f"single file cannot fit an 18 MiB volume: {name}")
        if size + contribution > ARCHIVE_LIMIT:
            groups.append(current)
            current, size = [], 22
        current.append((name, data))
        size += contribution
    if current:
        groups.append(current)
    return groups


def zip_bytes(payloads: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=False) as archive:
        for name, data in payloads:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    data = buffer.getvalue()
    if len(data) > ARCHIVE_LIMIT:
        raise SnapshotError("ZIP volume exceeded the 18 MiB transport limit")
    return data


def atomic_output(target: Path, data: bytes) -> None:
    no_symlink_chain(target.parent, target)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".snapshot-", suffix=".tmp",
                                         dir=target.parent, delete=False) as stream:
            temporary_name = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def build(root: Path, git: str, check_only: bool = False, working_tree: bool = False) -> dict:
    root = root.absolute()
    if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise SnapshotError("repository root must not be a symlink or junction")
    payloads, excluded, index, fingerprints = collect(root, git, working_tree)
    groups = groups_for(payloads)  # Enforce the compressed single-file limit in check-only too.
    selection_mode = "working-tree" if working_tree else "index"
    source = {"selection_mode": selection_mode, "bytes": "working-tree",
              "listing_sha256" if working_tree else "index_sha256": digest(index)}
    result = {"mode": selection_mode + ("-check-only" if check_only else "-build"),
              "files": len(payloads), "bytes": sum(len(x[1]) for x in payloads),
              "volumes": len(groups), "excluded": excluded,
              "source": source,
              "requires_staged_changes": not working_tree}
    if check_only:
        assert_stable(git, root, index, fingerprints, working_tree)
        return result
    manifest = {
        "format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "limits": {"archive_bytes": ARCHIVE_LIMIT, "file_bytes": FILE_LIMIT,
                   "total_bytes": TOTAL_LIMIT, "file_count": FILE_COUNT_LIMIT},
        "archives": [], "files": [], "excluded": excluded,
    }
    volumes = []
    for number, group in enumerate(groups, 1):
        archive_name = f"snapshot-{number:03d}.zip"
        packed = zip_bytes(group)
        manifest["archives"].append({
            "name": archive_name, "size": len(packed), "sha256": digest(packed),
            "file_count": len(group), "uncompressed_size": sum(len(x[1]) for x in group),
        })
        for name, data in group:
            manifest["files"].append({"path": name, "archive": archive_name,
                                      "size": len(data), "sha256": digest(data)})
        volumes.append((archive_name, packed))
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(manifest_bytes) > MANIFEST_LIMIT:
        raise SnapshotError("snapshot manifest exceeds 4 MiB budget")
    # Prevent mismatched snapshots if another process edits or stages files while compressing.
    assert_stable(git, root, index, fingerprints, working_tree)
    output = root / ".github-upload"
    no_symlink_chain(root, output)
    output.mkdir(exist_ok=True)
    for name, data in volumes:
        atomic_output(output / name, data)
    atomic_output(output / "snapshot-manifest.json", manifest_bytes)
    result["output"] = str(output)
    result["archives"] = manifest["archives"]
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--git", help="Git executable path if it is not on PATH")
    parser.add_argument("--check-only", action="store_true",
                        help="inspect selected working-tree files without creating archives")
    parser.add_argument("--working-tree", action="store_true",
                        help="use read-only git ls-files for tracked and non-ignored untracked files; no staging required")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.root, find_git(args.git), args.check_only, args.working_tree), ensure_ascii=False))
        return 0
    except (SnapshotError, OSError, UnicodeError) as exc:
        print(f"Snapshot build refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

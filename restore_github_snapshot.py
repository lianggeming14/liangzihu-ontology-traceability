#!/usr/bin/env python3
"""Verify and restore a bounded GitHub upload snapshot using only the standard library."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import unicodedata
import zipfile

FORMAT = "liangzihu-github-snapshot/1"
MIB = 1024 * 1024
ARCHIVE_LIMIT = 18 * MIB
FILE_LIMIT = 20 * MIB
TOTAL_LIMIT = 150 * MIB
FILE_COUNT_LIMIT = 2000
MANIFEST_LIMIT = 4 * MIB
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
ARCHIVE_RE = re.compile(r"snapshot-[0-9]{3,4}\.zip\Z")
SECRET_PATTERNS = (
    re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
)
PRIVATE_DIRS = {".git", ".ssh", ".aws", ".azure", ".gcloud", ".kube", ".codex",
                ".kimi", ".kimi-runtime", ".kimi-skills", ".gnupg", "credentials", "secrets"}
CACHE_DIRS = {".deps", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10))}


class SnapshotError(ValueError):
    pass


def checked_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 2048:
        raise SnapshotError("invalid relative path")
    if "\\" in value or value.startswith("/") or any(ord(c) < 32 for c in value):
        raise SnapshotError(f"unsafe path: {value!r}")
    parts = value.split("/")
    if any(p in ("", ".", "..") or ":" in p or p.endswith((" ", "."))
           or p.split(".")[0].casefold() in RESERVED for p in parts):
        raise SnapshotError(f"unsafe path: {value!r}")
    if unicodedata.normalize("NFC", value) != value or PurePosixPath(value).is_absolute():
        raise SnapshotError(f"noncanonical path: {value!r}")
    return value


def workflow_path(value: str) -> bool:
    parts = value.casefold().split("/")
    return any(parts[i:i + 2] == [".github", "workflows"] for i in range(len(parts) - 1))


def forbidden_reason(value: str) -> str | None:
    parts = value.casefold().split("/")
    name = parts[-1]
    if any(p in PRIVATE_DIRS for p in parts):
        return "private metadata or credential directory"
    if any(p in CACHE_DIRS for p in parts):
        return "dependency or generated cache"
    if parts[0] == "%systemdrive%":
        return "local operating-system cache"
    if name.startswith(".env") and name not in {".env.example", ".env.sample", ".env.template"}:
        return "local environment configuration"
    if (name in {"api-tokens.json", "pg-local-password.txt", "id_rsa", "id_ed25519",
                 ".netrc", ".npmrc", ".pypirc", "credentials.json", "credentials",
                 "secrets.json", "token.json", "tokens.json"}
            or re.search(r"(?:password|credential|secret|api[-_]?token)", name)
            and not name.endswith((".py", ".js", ".cjs", ".md", ".txt.example", ".json.example"))
            or name.endswith((".pem", ".key", ".pfx", ".p12"))):
        return "credential-like filename"
    if parts[:2] == ["implementation", "data"]:
        return "local database, assets, or backup"
    database_name = re.search(r"\.(?:db|sqlite|sqlite3)(?:[-.]|$)", name)
    sql_source = name.endswith((".sqlite.sql", ".sqlite3.sql", ".db.sql"))
    if (database_name and not sql_source) or name.endswith(("-wal", "-shm", ".pyc")):
        return "runtime database or compiled cache"
    if parts[:2] == ["implementation", "runtime"] and (
            len(parts) > 2 and parts[2] in {"pg-data", "postgresql"}
            or name.startswith("pg-") and name.endswith(".log")):
        return "local PostgreSQL runtime"
    if any(p.startswith("agri-ui-") for p in parts):
        return "temporary browser test data"
    if name.startswith("kimi-") and name.endswith((".log", ".jsonl")):
        return "local Kimi run log"
    return None


def transport_reason(value: str) -> str | None:
    parts = value.casefold().split("/")
    if ".github-upload" in parts:
        return "upload transport output"
    if len(parts) == 1 and (ARCHIVE_RE.fullmatch(parts[0])
                          or parts[0] in {"snapshot-manifest.json", "restore_github_snapshot.py"}):
        return "previous root-level upload transport"
    if workflow_path(value):
        return "workflow is uploaded and reviewed separately"
    return None


def scan_secrets(data: bytes, label: str) -> None:
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        raise SnapshotError(f"possible credential detected; path only: {label}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def integer(value: object, label: str, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise SnapshotError(f"invalid {label}")
    return value


def sha(value: object) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise SnapshotError("invalid SHA-256")
    return value


def no_symlink_chain(root: Path, target: Path) -> None:
    """Reject existing symlinks/junctions below an explicitly supplied root."""
    try:
        rel = target.relative_to(root)
    except ValueError as exc:
        raise SnapshotError("destination escapes root") from exc
    current = root
    for part in ("", *rel.parts):
        if part:
            current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise SnapshotError(f"symlink or junction not allowed: {current}")
        if current.exists() and current != target and not current.is_dir():
            raise SnapshotError(f"parent is not a directory: {current}")


def parse_json(data: bytes) -> dict:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SnapshotError("duplicate JSON key")
            result[key] = value
        return result
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("invalid manifest JSON") from exc
    if not isinstance(result, dict):
        raise SnapshotError("manifest must be an object")
    return result


def load_verified(manifest_path: Path) -> tuple[dict, list[tuple[str, bytes]]]:
    """Read archives only beside the manifest; perform every content check before writing."""
    manifest_path = manifest_path.absolute()
    no_symlink_chain(manifest_path.parent, manifest_path)
    if not manifest_path.is_file() or manifest_path.stat().st_size > MANIFEST_LIMIT:
        raise SnapshotError("manifest missing or oversized")
    with manifest_path.open("rb") as stream:
        manifest_bytes = stream.read(MANIFEST_LIMIT + 1)
    if len(manifest_bytes) > MANIFEST_LIMIT:
        raise SnapshotError("manifest oversized")
    manifest = parse_json(manifest_bytes)
    if manifest.get("format") != FORMAT:
        raise SnapshotError("unsupported snapshot format")
    archives, files = manifest.get("archives"), manifest.get("files")
    if not isinstance(archives, list) or not 1 <= len(archives) <= FILE_COUNT_LIMIT:
        raise SnapshotError("invalid archive list")
    if not isinstance(files, list) or not 1 <= len(files) <= FILE_COUNT_LIMIT:
        raise SnapshotError("file count budget exceeded or empty")
    archive_map, compressed_total = {}, 0
    if len(archives) > len(files):
        raise SnapshotError("too many archives for the declared file count")
    for entry in archives:
        if not isinstance(entry, dict):
            raise SnapshotError("invalid archive record")
        name = entry.get("name")
        if not isinstance(name, str) or not ARCHIVE_RE.fullmatch(name) or name in archive_map:
            raise SnapshotError("invalid or duplicate archive name")
        compressed_total += integer(entry.get("size"), "archive size", ARCHIVE_LIMIT)
        if compressed_total > TOTAL_LIMIT:
            raise SnapshotError("total compressed budget exceeded")
        if integer(entry.get("file_count"), "archive file count", FILE_COUNT_LIMIT) < 1:
            raise SnapshotError("empty archives are not allowed")
        integer(entry.get("uncompressed_size"), "archive expanded size", TOTAL_LIMIT)
        sha(entry.get("sha256"))
        archive_map[name] = entry
    file_map, folded, total = {}, set(), 0
    for entry in files:
        if not isinstance(entry, dict):
            raise SnapshotError("invalid file record")
        name = checked_path(entry.get("path"))
        reason = forbidden_reason(name) or transport_reason(name)
        if reason:
            raise SnapshotError(f"prohibited restore path ({reason}): {name}")
        if name.casefold() in folded:
            raise SnapshotError(f"duplicate or case-colliding file: {name}")
        folded.add(name.casefold())
        if entry.get("archive") not in archive_map:
            raise SnapshotError(f"unknown archive for: {name}")
        total += integer(entry.get("size"), "file size", FILE_LIMIT)
        sha(entry.get("sha256"))
        if total > TOTAL_LIMIT:
            raise SnapshotError("total uncompressed budget exceeded")
        file_map[name] = entry
    # A file cannot also be a parent directory, including case-insensitive collisions.
    for name in file_map:
        parts = name.casefold().split("/")
        if any("/".join(parts[:i]) in folded for i in range(1, len(parts))):
            raise SnapshotError(f"file/directory path collision: {name}")
    payloads, seen = [], set()
    for archive_name, record in archive_map.items():
        archive_path = manifest_path.parent / archive_name
        no_symlink_chain(manifest_path.parent, archive_path)
        if not archive_path.is_file() or archive_path.stat().st_size != record["size"]:
            raise SnapshotError(f"archive size mismatch: {archive_name}")
        with archive_path.open("rb") as stream:
            archive_bytes = stream.read(ARCHIVE_LIMIT + 1)
        if (len(archive_bytes) != record["size"] or len(archive_bytes) > ARCHIVE_LIMIT
                or digest(archive_bytes) != record["sha256"]):
            raise SnapshotError(f"archive SHA-256 mismatch: {archive_name}")
        expanded = 0
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                entries = archive.infolist()
                if len(entries) != record["file_count"] or len(entries) > FILE_COUNT_LIMIT:
                    raise SnapshotError(f"archive file count mismatch: {archive_name}")
                for info in entries:
                    name = checked_path(info.filename)
                    if info.orig_filename != info.filename:
                        raise SnapshotError("noncanonical ZIP member name")
                    mode = (info.external_attr >> 16) & 0o170000
                    if info.is_dir() or mode not in (0, stat.S_IFREG) or info.flag_bits & 1:
                        raise SnapshotError(f"nonregular or encrypted archive entry: {name}")
                    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        raise SnapshotError(f"unsupported compression: {name}")
                    expected = file_map.get(name)
                    if name in seen or expected is None or expected["archive"] != archive_name:
                        raise SnapshotError(f"unexpected or duplicate archive entry: {name}")
                    if info.file_size != expected["size"] or info.file_size > FILE_LIMIT:
                        raise SnapshotError(f"expanded size mismatch: {name}")
                    with archive.open(info) as stream:
                        data = stream.read(FILE_LIMIT + 1)
                    if len(data) != expected["size"] or digest(data) != expected["sha256"]:
                        raise SnapshotError(f"file SHA-256 or size mismatch: {name}")
                    scan_secrets(data, name)
                    expanded += len(data)
                    seen.add(name)
                    payloads.append((name, data))
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError, NotImplementedError) as exc:
            raise SnapshotError(f"invalid archive: {archive_name}") from exc
        if expanded != record["uncompressed_size"]:
            raise SnapshotError(f"archive expanded-size mismatch: {archive_name}")
    if seen != set(file_map):
        raise SnapshotError("manifest files missing from archives")
    return manifest, payloads


def restore(manifest_path: Path, destination: Path) -> dict:
    _, payloads = load_verified(manifest_path)
    destination = destination.absolute()
    # Do not resolve a user-supplied symlink to silently change the write destination.
    if destination.is_symlink() or (hasattr(destination, "is_junction") and destination.is_junction()):
        raise SnapshotError("destination must not be a symlink or junction")
    if destination.exists() and not destination.is_dir():
        raise SnapshotError("destination must be a directory")
    for name, _ in payloads:
        target = destination.joinpath(*name.split("/"))
        no_symlink_chain(destination, target)
        if target.exists() and not target.is_file():
            raise SnapshotError(f"target is not a regular file: {name}")
    # Validation is finished. Never delete existing destination files.
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".snapshot-restore-", dir=destination) as staging:
        staged = []
        for index, (name, data) in enumerate(payloads):
            temporary = Path(staging) / str(index)
            temporary.write_bytes(data)
            staged.append((name, temporary))
        for name, temporary in staged:
            target = destination.joinpath(*name.split("/"))
            no_symlink_chain(destination, target)
            target.parent.mkdir(parents=True, exist_ok=True)
            no_symlink_chain(destination, target)
            os.replace(temporary, target)
    return {"restored_files": len(payloads), "restored_bytes": sum(len(x[1]) for x in payloads),
            "destination": str(destination), "deleted_files": 0}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("snapshot-manifest.json"))
    parser.add_argument("--destination", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        print(json.dumps(restore(args.manifest, args.destination), ensure_ascii=False))
        return 0
    except (SnapshotError, OSError) as exc:
        print(f"Snapshot restore refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

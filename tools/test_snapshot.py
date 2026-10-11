"""Standard-library regression tests; all repositories and restores are isolated temporary data."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_github_snapshot as builder
import restore_github_snapshot as restorer


def make_archive(folder, entries, *, manifest_changes=None, file_changes=None):
    """entries: (name, bytes[, Unix file-type bits])."""
    folder.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            name, data = entry[:2]
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = ((entry[2] if len(entry) > 2 else stat.S_IFREG) | 0o644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    packed = buffer.getvalue()
    (folder / "snapshot-001.zip").write_bytes(packed)
    records = [{"path": entry[0], "archive": "snapshot-001.zip", "size": len(entry[1]),
                "sha256": restorer.digest(entry[1])} for entry in entries]
    if file_changes:
        file_changes(records)
    manifest = {
        "format": restorer.FORMAT,
        "archives": [{"name": "snapshot-001.zip", "size": len(packed),
                      "sha256": restorer.digest(packed), "file_count": len(entries),
                      "uncompressed_size": sum(len(x[1]) for x in entries)}],
        "files": records, "excluded": [],
    }
    if manifest_changes:
        manifest_changes(manifest)
    output = folder / "snapshot-manifest.json"
    output.write_text(json.dumps(manifest), encoding="utf-8")
    return output


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.git = builder.find_git()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ontology-snapshot-test-")
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git_run("init", "-q")
        self.git_run("config", "--local", "core.autocrlf", "false")

    def tearDown(self):
        self.temporary.cleanup()

    def git_run(self, *args):
        return builder.git_call(self.git, self.repo, *args)

    def stage(self, files):
        for name, data in files.items():
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.git_run("add", "-A")

    def refused(self, manifest):
        dest = self.base / "dest"
        dest.mkdir(exist_ok=True)
        (dest / "keep.txt").write_bytes(b"original")
        with self.assertRaises(restorer.SnapshotError):
            restorer.restore(manifest, dest)
        self.assertEqual((dest / "keep.txt").read_bytes(), b"original")
        self.assertEqual(sorted(p.name for p in dest.iterdir()), ["keep.txt"])

    def test_complete_real_git_round_trip_and_preserve_unrelated_file(self):
        files = {"中文目录/方案.txt": "智慧农业\r\n跨域溯源\n".encode(),
                 "code/main.py": b"print('example')\r\n", "empty.txt": b"",
                 "binary.dat": bytes(range(256)) * 7}
        self.stage(files)
        result = builder.build(self.repo, self.git)
        self.assertEqual(result["files"], len(files))
        dest = self.base / "restored"
        dest.mkdir()
        (dest / "not-in-snapshot.txt").write_bytes(b"preserved")
        actual = restorer.restore(self.repo / ".github-upload/snapshot-manifest.json", dest)
        self.assertEqual(actual["deleted_files"], 0)
        self.assertEqual(actual["restored_files"], len(files))
        for name, data in files.items():
            self.assertEqual(hashlib.sha256((dest / name).read_bytes()).digest(),
                             hashlib.sha256(data).digest())
        self.assertEqual((dest / "not-in-snapshot.txt").read_bytes(), b"preserved")

    def test_real_two_volume_boundary_and_restore_hashes(self):
        files = {"a.bin": os.urandom(10 * restorer.MIB), "b.bin": os.urandom(10 * restorer.MIB)}
        self.stage(files)
        result = builder.build(self.repo, self.git)
        self.assertEqual(result["volumes"], 2)
        self.assertTrue(all(x["size"] <= 18 * restorer.MIB for x in result["archives"]))
        dest = self.base / "multi"
        restorer.restore(self.repo / ".github-upload/snapshot-manifest.json", dest)
        for name, data in files.items():
            self.assertEqual(restorer.digest((dest / name).read_bytes()), restorer.digest(data))

    def test_check_only_creates_no_output_and_lists_transport_exclusions(self):
        self.stage({"app.py": b"pass\n", ".github/workflows/import.yml": b"name: import\n",
                    "snapshot-001.zip": b"old transport", "snapshot-manifest.json": b"{}",
                    "restore_github_snapshot.py": b"# transport copy\n",
                    "tools/restore_github_snapshot.py": b"# real project file\n"})
        result = builder.build(self.repo, self.git, check_only=True)
        self.assertFalse((self.repo / ".github-upload").exists())
        self.assertEqual(result["files"], 2)
        self.assertEqual(len(result["excluded"]), 4)

    def test_working_tree_includes_unstaged_and_untracked_respects_ignore_without_index_write(self):
        self.stage({"tracked.txt": b"staged original\n", ".gitignore": b"ignored/\n.github-upload/\n"})
        (self.repo / "tracked.txt").write_bytes(b"unstaged edit\r\n")
        (self.repo / "new.txt").write_bytes(b"new untracked\n")
        (self.repo / "ignored").mkdir()
        (self.repo / "ignored/api-tokens.json").write_bytes(b"not inspected")
        index_before = (self.repo / ".git/index").read_bytes()
        calls = []
        original_call = builder.git_call
        def audit(git, root, *args, **kwargs):
            calls.append(args)
            return original_call(git, root, *args, **kwargs)
        with patch.object(builder, "git_call", side_effect=audit):
            result = builder.build(self.repo, self.git, working_tree=True)
        self.assertEqual(result["mode"], "working-tree-build")
        self.assertEqual(result["source"]["selection_mode"], "working-tree")
        self.assertFalse(result["requires_staged_changes"])
        self.assertNotIn("index_sha256", result["source"])
        self.assertEqual((self.repo / ".git/index").read_bytes(), index_before)
        self.assertTrue(all(args[0] in {"rev-parse", "ls-files"} for args in calls))
        self.assertIn(("ls-files", "--cached", "--others", "--exclude-standard", "-z"), calls)
        dest = self.base / "worktree-restored"
        restorer.restore(self.repo / ".github-upload/snapshot-manifest.json", dest)
        self.assertEqual((dest / "tracked.txt").read_bytes(), b"unstaged edit\r\n")
        self.assertEqual((dest / "new.txt").read_bytes(), b"new untracked\n")
        self.assertFalse((dest / "ignored").exists())

    def test_working_tree_check_only_supports_empty_index_and_cli(self):
        (self.repo / "new.txt").write_bytes(b"untracked only\n")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = builder.main(["--root", str(self.repo), "--git", self.git,
                                   "--working-tree", "--check-only"])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["mode"], "working-tree-check-only")
        self.assertEqual(result["files"], 1)
        self.assertFalse((self.repo / ".github-upload").exists())
        self.assertFalse((self.repo / ".git/index").exists())

    def test_working_tree_new_file_during_inspection_is_refused(self):
        (self.repo / "one.txt").write_bytes(b"one\n")
        original = builder.groups_for
        def mutate(payloads):
            (self.repo / "two.txt").write_bytes(b"two\n")
            return original(payloads)
        with patch.object(builder, "groups_for", side_effect=mutate):
            with self.assertRaisesRegex(restorer.SnapshotError, "file list changed"):
                builder.build(self.repo, self.git, working_tree=True)
        self.assertFalse((self.repo / ".github-upload").exists())

    def test_working_tree_content_change_during_inspection_is_refused(self):
        target = self.repo / "one.txt"
        target.write_bytes(b"one\n")
        original_stat = target.stat()
        original = builder.groups_for
        def mutate(payloads):
            target.write_bytes(b"two\n")
            os.utime(target, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            return original(payloads)
        with patch.object(builder, "groups_for", side_effect=mutate):
            with self.assertRaisesRegex(restorer.SnapshotError, "file changed"):
                builder.build(self.repo, self.git, working_tree=True)
        self.assertFalse((self.repo / ".github-upload").exists())

    def test_sqlite_migration_sources_round_trip_while_runtime_databases_remain_forbidden(self):
        sources = {
            "implementation/migrations/001_core.sqlite.sql": b"CREATE TABLE sample (id TEXT);\n",
            "migration.sqlite3.sql": b"CREATE TABLE sample2 (id TEXT);\n",
            "schema.db.sql": b"CREATE TABLE sample3 (id TEXT);\n",
        }
        self.stage(sources)
        result = builder.build(self.repo, self.git, working_tree=True)
        self.assertEqual(result["files"], len(sources))
        dest = self.base / "migration-restored"
        restorer.restore(self.repo / ".github-upload/snapshot-manifest.json", dest)
        for name, data in sources.items():
            self.assertIsNone(restorer.forbidden_reason(name))
            self.assertEqual((dest / name).read_bytes(), data)
        for name in ["x.sqlite", "x.sqlite3", "x.db", "x.sqlite-wal", "x.sqlite3-shm",
                     "x.db-wal", "x.db-shm", "x.db.bak", "x.db.uuid.pending-shm"]:
            with self.subTest(path=name):
                self.assertIsNotNone(restorer.forbidden_reason(name))
                manifest = make_archive(self.base / ("bad-" + name), [(name, b"runtime")])
                self.refused(manifest)

    def test_workflow_secrets_are_checked_even_though_workflow_is_excluded(self):
        fake_secret = b"ghp_" + b"A" * 40
        self.stage({"app.py": b"pass\n", ".github/workflows/import.yml": fake_secret})
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            status = builder.main(["--root", str(self.repo), "--git", self.git, "--check-only"])
        self.assertEqual(status, 1)
        self.assertIn(".github/workflows/import.yml", captured.getvalue())
        self.assertNotIn(fake_secret.decode(), captured.getvalue())

    def test_sensitive_index_path_is_refused_not_silently_omitted(self):
        self.stage({"app.py": b"pass\n", "implementation/data/api-tokens.json": b"{}"})
        with self.assertRaisesRegex(restorer.SnapshotError, "prohibited indexed file"):
            builder.build(self.repo, self.git, check_only=True)
        self.assertFalse((self.repo / ".github-upload").exists())

    def test_unstaged_changes_are_refused(self):
        self.stage({"app.py": b"old\n"})
        (self.repo / "app.py").write_bytes(b"new content\n")
        with self.assertRaisesRegex(restorer.SnapshotError, "not staged"):
            builder.build(self.repo, self.git, check_only=True)

    def test_index_change_during_compression_is_refused(self):
        self.stage({"app.py": b"old\n"})
        original = builder.groups_for
        def mutate(payloads):
            self.stage({"app.py": b"new content\n"})
            return original(payloads)
        with patch.object(builder, "groups_for", side_effect=mutate):
            with self.assertRaisesRegex(restorer.SnapshotError, "index changed"):
                builder.build(self.repo, self.git)
        self.assertFalse((self.repo / ".github-upload").exists())

    def test_content_change_with_preserved_size_and_time_is_refused(self):
        self.stage({"app.py": b"old\n"})
        target = self.repo / "app.py"
        original_stat = target.stat()
        original = builder.groups_for
        def mutate(payloads):
            target.write_bytes(b"new\n")
            os.utime(target, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            return original(payloads)
        with patch.object(builder, "groups_for", side_effect=mutate):
            with self.assertRaises(restorer.SnapshotError):
                builder.build(self.repo, self.git)
        self.assertFalse((self.repo / ".github-upload").exists())

    def test_total_compressed_budget_is_enforced(self):
        def excessive(m):
            m["archives"] = [{"name": f"snapshot-{i:03d}.zip", "size": restorer.ARCHIVE_LIMIT,
                              "sha256": "0" * 64, "file_count": 1, "uncompressed_size": 0}
                             for i in range(1, 10)]
            m["files"] = [{"path": f"x{i}", "archive": f"snapshot-{i:03d}.zip",
                           "size": 0, "sha256": "0" * 64} for i in range(1, 10)]
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed")],
                                manifest_changes=excessive)
        self.refused(manifest)

    def test_source_file_over_twenty_mib_is_refused(self):
        self.stage({"large.bin": b"x" * (restorer.FILE_LIMIT + 1)})
        with self.assertRaisesRegex(restorer.SnapshotError, "oversized"):
            builder.build(self.repo, self.git, check_only=True)

    def test_single_incompressible_file_over_volume_limit_is_refused(self):
        self.stage({"large.bin": os.urandom(18 * restorer.MIB + 1)})
        with self.assertRaisesRegex(restorer.SnapshotError, "cannot fit"):
            builder.build(self.repo, self.git, check_only=True)

    def test_malicious_and_protected_paths_do_not_write_anything(self):
        paths = ["../escape.txt", "/absolute.txt", "C:/absolute.txt", r"..\escape.txt",
                 "a//b", "a/./b", "CON.txt", ".git/config", ".github/workflows/push.yml",
                 ".kimi-runtime/auth.json", ".aws/config", "implementation/data/agri.db",
                 "snapshot-001.zip", ".github-upload/a.txt", ".env", "id_rsa"]
        for index, name in enumerate(paths):
            with self.subTest(path=name):
                manifest = make_archive(self.base / f"bad-{index}",
                                        [("keep.txt", b"changed"), (name, b"bad")])
                self.refused(manifest)
        self.assertFalse((self.base / "escape.txt").exists())

    def test_zip_symlink_is_refused_before_overwrite(self):
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed"),
                                                   ("link", b"../../outside", stat.S_IFLNK)])
        self.refused(manifest)

    def test_duplicate_archive_entries_are_refused(self):
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed"),
                                                   ("same.txt", b"one"), ("same.txt", b"two")])
        self.refused(manifest)

    def test_case_collision_is_refused(self):
        manifest = make_archive(self.base / "bad", [("A.txt", b"one"), ("a.txt", b"two")])
        self.refused(manifest)

    def test_file_parent_collision_is_refused(self):
        manifest = make_archive(self.base / "bad", [("A", b"one"), ("a/b.txt", b"two")])
        self.refused(manifest)

    def test_archive_hash_mismatch_is_refused(self):
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed")],
                                manifest_changes=lambda m: m["archives"][0].update(sha256="0" * 64))
        self.refused(manifest)

    def test_file_hash_mismatch_is_refused_before_any_overwrite(self):
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed"), ("second", b"bad")],
                                file_changes=lambda rows: rows[1].update(sha256="0" * 64))
        self.refused(manifest)

    def test_extra_zip_member_is_refused(self):
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed"), ("extra", b"bad")],
                                file_changes=lambda rows: rows.pop())
        self.refused(manifest)

    def test_archive_path_must_be_in_manifest_directory(self):
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed")],
                                manifest_changes=lambda m: m["archives"][0].update(name="../else.zip"))
        self.refused(manifest)

    def test_total_expanded_budget_is_enforced_before_decompression(self):
        def oversized(m):
            m["files"] = [{"path": f"x{i}", "archive": "snapshot-001.zip",
                           "size": restorer.FILE_LIMIT, "sha256": "0" * 64} for i in range(8)]
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed")],
                                manifest_changes=oversized)
        self.refused(manifest)

    def test_file_count_budget_is_enforced(self):
        def excessive(m):
            m["files"] = [{"path": f"x{i}", "archive": "snapshot-001.zip",
                           "size": 0, "sha256": "0" * 64} for i in range(2001)]
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed")],
                                manifest_changes=excessive)
        self.refused(manifest)

    def test_oversized_file_metadata_is_refused(self):
        manifest = make_archive(self.base / "bad", [("keep.txt", b"changed")],
                                file_changes=lambda rows: rows[0].update(size=restorer.FILE_LIMIT + 1))
        self.refused(manifest)

    def test_destination_parent_file_is_refused(self):
        manifest = make_archive(self.base / "good", [("folder/file.txt", b"content")])
        dest = self.base / "dest"
        dest.mkdir()
        (dest / "folder").write_bytes(b"existing")
        with self.assertRaises(restorer.SnapshotError):
            restorer.restore(manifest, dest)
        self.assertEqual((dest / "folder").read_bytes(), b"existing")

    def test_destination_symlink_is_refused_when_supported(self):
        outside = self.base / "outside"
        outside.mkdir()
        dest = self.base / "dest"
        dest.mkdir()
        try:
            (dest / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("OS does not grant symlink creation to this test process")
        manifest = make_archive(self.base / "good", [("link/file.txt", b"bad")])
        with self.assertRaises(restorer.SnapshotError):
            restorer.restore(manifest, dest)
        self.assertFalse((outside / "file.txt").exists())

    def test_secret_inside_snapshot_is_refused_before_write(self):
        manifest = make_archive(self.base / "bad",
                                [("keep.txt", b"changed"), ("app.txt", b"ghp_" + b"B" * 40)])
        self.refused(manifest)

    def test_duplicate_json_keys_are_refused(self):
        manifest = self.base / "snapshot-manifest.json"
        manifest.write_bytes(b'{"format":"x","format":"y"}')
        self.refused(manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)

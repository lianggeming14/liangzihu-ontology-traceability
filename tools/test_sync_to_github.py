"""Offline workflow tests: real local Git repositories; no GitHub/network access.

The snapshot builder is a deliberately minimal fixture. Its safety/content checks
are covered separately by test_snapshot.py, not by these orchestration tests.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sync_to_github_under_test", PROJECT_ROOT / "tools" / "sync_to_github.py")
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)
GIT = next((p for p in (
    "C:/Users/robot/.conda/envs/direct/Library/bin/git.exe",
    shutil.which("git"),
) if p and Path(p).is_file()), None)
REAL_RUN = subprocess.run
SUCCESS_SCAN = "import sys\nassert sys.argv[1:] == ['--check-only']\n"


@unittest.skipUnless(GIT, "Git executable is required for offline integration tests")
class SyncWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary_root = PROJECT_ROOT / ".github-upload"
        temporary_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="sync-tests-", dir=temporary_root)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
                        GCM_INTERACTIVE="never")

    def git(self, cwd, *args):
        # The exception is scoped to this exact fixture path on every invocation.
        # Do not change global Git settings or point any remote at GitHub.
        result = REAL_RUN([GIT, "-c", "safe.directory=" + cwd.as_posix(),
                           "-c", "user.name=Offline Test",
                           "-c", "user.email=offline@example.invalid", *args],
                          cwd=cwd, env=self.env, text=True, encoding="utf-8",
                          capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return result.stdout

    def write(self, repository, name, content):
        target = repository / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def fixture(self, name, checkout=False):
        base = self.base / name
        remote, author, work = (base / part for part in ("remote.git", "author", "work"))
        for path in (remote, author, work):
            path.mkdir(parents=True)
        self.git(remote, "init", "--bare", "-b", "main")
        self.git(author, "init", "-b", "main")
        self.write(author, "deliverable.txt", "remote baseline\n")
        self.write(author, "snapshot-manifest.json", '{"transport":true}\n')
        (author / "snapshot-001.zip").write_bytes(b"offline transport bytes")
        self.write(author, "tools/build_github_snapshot.py", SUCCESS_SCAN)
        self.git(author, "add", "-A")
        self.git(author, "commit", "-m", "Browser import baseline")
        self.git(author, "remote", "add", "origin", remote.as_posix())
        self.git(author, "push", "origin", "main")
        self.git(work, "init", "-b", "main")
        if checkout:
            self.git(work, "remote", "add", "origin", remote.as_posix())
            self.git(work, "fetch", "origin", "main")
            self.git(work, "reset", "--hard", "origin/main")
        return remote, author, work

    def invoke(self, remote, work):
        with mock.patch.object(sync, "ROOT", work), \
             mock.patch.object(sync, "REMOTE", remote.as_posix()), \
             mock.patch.object(sync, "find_git", return_value=GIT), \
             mock.patch.object(sys, "argv", ["sync_to_github.py", "--message", "Offline sync test"]), \
             mock.patch.dict(os.environ, self.env, clear=True), \
             redirect_stdout(io.StringIO()):
            sync.main()

    def test_unborn_bootstrap_preserves_local_content_and_remote_transport(self):
        remote, _, work = self.fixture("bootstrap")
        self.write(work, "deliverable.txt", "local restored work with edits\n")
        self.write(work, "新方案.txt", "仅在本地的新内容\n")
        self.write(work, "tools/build_github_snapshot.py", SUCCESS_SCAN)
        before = {p.relative_to(work).as_posix(): p.read_bytes()
                  for p in work.rglob("*") if p.is_file() and ".git" not in p.parts}
        self.invoke(remote, work)
        for relative, expected in before.items():
            self.assertEqual((work / relative).read_bytes(), expected, relative)
        self.assertEqual((work / "snapshot-001.zip").read_bytes(), b"offline transport bytes")
        self.assertEqual(self.git(remote, "show", "main:snapshot-manifest.json"), '{"transport":true}\n')
        self.assertEqual(self.git(remote, "show", "main:deliverable.txt"), "local restored work with edits\n")
        self.assertEqual(self.git(remote, "show", "main:新方案.txt"), "仅在本地的新内容\n")
        self.assertEqual(self.git(work, "rev-parse", "HEAD"), self.git(remote, "rev-parse", "main"))
        self.assertEqual(self.git(work, "status", "--porcelain"), "")
        self.assertEqual(self.git(remote, "rev-list", "--count", "main").strip(), "2")

    def test_remote_divergence_and_dirty_worktree_stop_without_overwrite(self):
        for scenario in ("divergent_clean", "remote_ahead_dirty"):
            with self.subTest(scenario=scenario):
                remote, author, work = self.fixture(scenario, checkout=True)
                if scenario == "divergent_clean":
                    self.write(work, "local-only.txt", "committed local branch\n")
                    self.git(work, "add", "-A")
                    self.git(work, "commit", "-m", "Local independent commit")
                else:
                    self.write(work, "deliverable.txt", "staged local edit\n")
                    self.git(work, "add", "deliverable.txt")
                    self.write(work, "deliverable.txt", "unstaged local edit\n")
                    self.write(work, "local-only.txt", "untracked local file\n")
                self.write(author, "remote-only.txt", "remote independent addition\n")
                self.git(author, "add", "-A")
                self.git(author, "commit", "-m", "Remote advanced")
                self.git(author, "push", "origin", "main")
                local_head = self.git(work, "rev-parse", "HEAD")
                remote_head = self.git(remote, "rev-parse", "main")
                status = self.git(work, "status", "--porcelain")
                staged = self.git(work, "diff", "--cached", "--binary")
                unstaged = self.git(work, "diff", "--binary")
                local_bytes = (work / "local-only.txt").read_bytes()
                with self.assertRaises(RuntimeError):
                    self.invoke(remote, work)
                self.assertEqual(self.git(work, "rev-parse", "HEAD"), local_head)
                self.assertEqual(self.git(remote, "rev-parse", "main"), remote_head)
                self.assertEqual(self.git(work, "status", "--porcelain"), status)
                self.assertEqual(self.git(work, "diff", "--cached", "--binary"), staged)
                self.assertEqual(self.git(work, "diff", "--binary"), unstaged)
                self.assertEqual((work / "local-only.txt").read_bytes(), local_bytes)
                self.assertFalse((work / "remote-only.txt").exists())

    def test_failed_scan_never_commits_or_pushes(self):
        remote, _, work = self.fixture("failed_scan", checkout=True)
        head = self.git(work, "rev-parse", "HEAD")
        remote_head = self.git(remote, "rev-parse", "main")
        self.write(work, "deliverable.txt", "edits must survive rejection\n")
        self.write(work, "tools/build_github_snapshot.py",
                   "import sys\nassert sys.argv[1:] == ['--check-only']\nraise SystemExit(9)\n")
        with mock.patch.object(sync.subprocess, "run", wraps=REAL_RUN) as calls:
            with self.assertRaisesRegex(RuntimeError, "提交前文件检查未通过"):
                self.invoke(remote, work)
        commands = [call.args[0] for call in calls.call_args_list]
        self.assertEqual(sum("--check-only" in cmd for cmd in commands), 1)
        git_commands = [cmd for cmd in commands if cmd[0] == GIT]
        self.assertFalse(any("commit" in cmd or "push" in cmd for cmd in git_commands))
        self.assertTrue(all("safe.directory=" + work.as_posix() in cmd for cmd in git_commands))
        self.assertEqual(self.git(work, "rev-parse", "HEAD"), head)
        self.assertEqual(self.git(remote, "rev-parse", "main"), remote_head)
        self.assertEqual((work / "deliverable.txt").read_text(encoding="utf-8"), "edits must survive rejection\n")


if __name__ == "__main__":
    unittest.main()

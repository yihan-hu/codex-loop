import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from codex_loop_runtime import workspace
from codex_loop_runtime.host_config import configured_git_metadata_for_path


def init_external_repo(worktree: Path, git_dir: Path) -> None:
    worktree.mkdir(parents=True)
    git_dir.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", f"--separate-git-dir={git_dir}", str(worktree)], check=True)
    (worktree / "tracked.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(worktree), "add", "tracked.txt"], check=True)
    subprocess.run([
        "git", "-C", str(worktree), "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", "init",
    ], check=True)


def write_profile(home: Path, worktree: Path, metadata_root: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 4,
        "workspace": {"environments": {"wsl": {
            "projects": {"demo": str(worktree)},
            "git_metadata_root": str(metadata_root),
        }}},
    }
    path = home / "host.json"
    path.write_text(json.dumps(payload))
    if os.name != "nt":
        os.chmod(path, 0o600)


class SharedGitMetadataRepairTests(unittest.TestCase):
    def test_wrong_host_pointer_is_repaired_only_after_normal_probe_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            worktree = root / "OneDrive" / "demo"
            metadata_root = root / "git-meta"
            git_dir = metadata_root / "demo"
            init_external_repo(worktree, git_dir)
            (worktree / ".git").write_text("gitdir: /Users/other-host/.git-meta/demo\n")
            home = root / "codex-home"
            write_profile(home, worktree, metadata_root)
            with patch.dict(os.environ, {"CODEX_LOOP_HOME": str(home)}):
                self.assertEqual(configured_git_metadata_for_path(worktree / "tracked.txt")["git_dir"], str(git_dir))
                self.assertEqual(workspace.repo_root(worktree), worktree.resolve())
                self.assertEqual((worktree / ".git").read_text(), f"gitdir: {git_dir.resolve()}\n")
                self.assertTrue(workspace.is_git_repo(worktree))

    def test_broken_synced_dotgit_directory_is_preserved_outside_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            worktree = root / "OneDrive" / "demo"
            metadata_root = root / "git-meta"
            git_dir = metadata_root / "demo"
            init_external_repo(worktree, git_dir)
            (worktree / ".git").unlink()
            bad = worktree / ".git"
            bad.mkdir()
            (bad / "HEAD").write_text("ref: refs/heads/master\n")
            home = root / "codex-home"
            write_profile(home, worktree, metadata_root)
            with patch.dict(os.environ, {"CODEX_LOOP_HOME": str(home)}):
                self.assertEqual(workspace.repo_root(worktree), worktree.resolve())
                backup = metadata_root / ".codex-loop-recovered" / "demo-shared-dotgit"
                self.assertTrue(backup.is_dir())
                self.assertEqual((backup / "HEAD").read_text(), "ref: refs/heads/master\n")
                self.assertEqual((worktree / ".git").read_text(), f"gitdir: {git_dir.resolve()}\n")

    def test_valid_but_wrong_unborn_synced_repo_repairs_during_git_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            worktree = root / "OneDrive" / "demo"
            metadata_root = root / "git-meta"
            git_dir = metadata_root / "demo"
            init_external_repo(worktree, git_dir)
            (worktree / ".git").unlink()
            subprocess.run(["git", "init", "-q", str(worktree)], check=True)
            # The synced .git directory is a valid repository, but it is unborn and has
            # replaced the host-local metadata that already has committed history.
            self.assertEqual(subprocess.run(["git", "-C", str(worktree), "rev-parse", "--show-toplevel"],
                                            capture_output=True).returncode, 0)
            home = root / "codex-home"
            write_profile(home, worktree, metadata_root)
            with patch.dict(os.environ, {"CODEX_LOOP_HOME": str(home)}):
                state = workspace.git_state(worktree, include_content_hashes=False)
                self.assertEqual(state["head"], subprocess.check_output(
                    ["git", "--git-dir", str(git_dir), "rev-parse", "HEAD"], text=True).strip())
                backup = metadata_root / ".codex-loop-recovered" / "demo-shared-dotgit"
                self.assertTrue(backup.is_dir())
                self.assertTrue((worktree / ".git").is_file())

    def test_git_probe_respects_repository_filemode_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            worktree = root / "demo"
            subprocess.run(["git", "init", "-q", str(worktree)], check=True)
            tracked = worktree / "tracked.txt"
            tracked.write_text("one\n")
            subprocess.run(["git", "-C", str(worktree), "add", "tracked.txt"], check=True)
            subprocess.run([
                "git", "-C", str(worktree), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-qm", "init",
            ], check=True)
            subprocess.run(["git", "-C", str(worktree), "config", "core.filemode", "false"], check=True)
            tracked.chmod(0o755)
            self.assertEqual(
                subprocess.check_output(["git", "-C", str(worktree), "status", "--porcelain"], text=True),
                "",
            )
            state = workspace.git_state(worktree, include_content_hashes=False)
            self.assertEqual(state["status"], [])
            self.assertFalse(state["probe_degraded"])

    def test_normal_git_repo_does_not_enter_repair_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            worktree = root / "demo"
            subprocess.run(["git", "init", "-q", str(worktree)], check=True)
            marker = worktree / ".git"
            home = root / "codex-home"
            metadata_root = root / "git-meta"
            write_profile(home, worktree, metadata_root)
            before = marker.stat().st_mtime_ns
            with patch.dict(os.environ, {"CODEX_LOOP_HOME": str(home)}):
                self.assertEqual(workspace.repo_root(worktree), worktree.resolve())
            self.assertTrue(marker.is_dir())
            self.assertEqual(marker.stat().st_mtime_ns, before)

    def test_git_metadata_root_inside_shared_worktree_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            worktree = root / "OneDrive" / "demo"
            metadata_root = worktree / ".host-git"
            git_dir = metadata_root / "demo"
            init_external_repo(worktree, git_dir)
            (worktree / ".git").write_text("gitdir: /missing/other-host/repo\n")
            home = root / "codex-home"
            write_profile(home, worktree, metadata_root)
            with patch.dict(os.environ, {"CODEX_LOOP_HOME": str(home)}):
                with self.assertRaisesRegex(RuntimeError, "must stay outside"):
                    workspace.repo_root(worktree)

    def test_unregistered_or_missing_external_metadata_is_not_repaired(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            worktree = root / "OneDrive" / "demo"
            worktree.mkdir(parents=True)
            (worktree / ".git").write_text("gitdir: /missing/other-host/repo\n")
            home = root / "codex-home"
            write_profile(home, worktree, root / "git-meta")
            before = (worktree / ".git").read_text()
            with patch.dict(os.environ, {"CODEX_LOOP_HOME": str(home)}):
                self.assertEqual(workspace.repo_root(worktree), worktree.resolve())
            self.assertEqual((worktree / ".git").read_text(), before)


if __name__ == "__main__":
    unittest.main()

import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


def run(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check
    )


def git(cwd: Path, *args: str) -> str:
    return run(cwd, *args).stdout.strip()


def configure(cwd: Path) -> None:
    run(cwd, "config", "user.name", "test")
    run(cwd, "config", "user.email", "test@example.com")


class WebPublishExactIdentityTests(unittest.TestCase):
    def fixture(self, base: Path):
        remote = base / "remote.git"
        run(base, "init", "--bare", "-q", str(remote))

        dev = base / "dev"
        dev.mkdir()
        run(dev, "init", "-q")
        configure(dev)
        (dev / "base.txt").write_text("base\n")
        run(dev, "add", ".")
        run(dev, "commit", "-qm", "base")
        base_commit = git(dev, "rev-parse", "HEAD")
        run(dev, "branch", "-M", "main")
        run(dev, "remote", "add", "origin", str(remote))
        run(dev, "push", "-q", "origin", "main")

        (dev / "source.txt").write_text("audited source\n")
        run(dev, "add", ".")
        run(dev, "commit", "-qm", "audited source")
        source_commit = git(dev, "rev-parse", "HEAD")
        source_tree = git(dev, "rev-parse", "HEAD^{tree}")
        bundle_ref = f"refs/heads/codex-loop-publish-{uuid.uuid4().hex}"
        run(dev, "update-ref", bundle_ref, source_commit)
        bundle = base / "source.bundle"
        run(dev, "bundle", "create", str(bundle), bundle_ref)
        run(dev, "update-ref", "-d", bundle_ref)
        self.assertEqual(run(dev, "bundle", "verify", str(bundle), check=False).returncode, 0)

        trigger = base / "trigger"
        run(base, "clone", "-q", str(remote), str(trigger))
        configure(trigger)
        run(trigger, "checkout", "-q", "-b", "main", base_commit)
        req = trigger / ".github" / "import-requests" / "request.json"
        req.parent.mkdir(parents=True)
        req.write_text("{}\n")
        run(trigger, "add", str(req.relative_to(trigger)))
        run(trigger, "commit", "-qm", "trigger")
        trigger_commit = git(trigger, "rev-parse", "HEAD")
        run(trigger, "push", "-q", "origin", "main")
        return remote, bundle, bundle_ref, base_commit, source_commit, source_tree, trigger_commit

    def importer_push(self, work: Path, remote: Path, bundle: Path, bundle_ref: str, base_commit: str, source_commit: str, source_tree: str, trigger_commit: str, *, check: bool = True):
        run(work.parent, "clone", "-q", str(remote), str(work))
        configure(work)
        remote_head = git(work, "ls-remote", "origin", "refs/heads/main").split()[0]
        self.assertEqual(remote_head, trigger_commit)
        self.assertEqual(run(work, "bundle", "verify", str(bundle), check=False).returncode, 0)
        staging_ref = "refs/codex-loop/publish"
        run(work, "fetch", str(bundle), f"{bundle_ref}:{staging_ref}")
        self.assertEqual(git(work, "rev-parse", staging_ref), source_commit)
        self.assertEqual(git(work, "rev-parse", f"{staging_ref}^{{tree}}"), source_tree)
        self.assertEqual(run(work, "merge-base", "--is-ancestor", base_commit, source_commit, check=False).returncode, 0)
        return run(
            work,
            "push",
            f"--force-with-lease=refs/heads/main:{trigger_commit}",
            "origin",
            f"{source_commit}:refs/heads/main",
            check=check,
        )

    def test_trigger_is_replaced_by_exact_audited_commit_and_tree(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            remote, bundle, bundle_ref, base_commit, source_commit, source_tree, trigger_commit = self.fixture(base)
            result = self.importer_push(base / "importer", remote, bundle, bundle_ref, base_commit, source_commit, source_tree, trigger_commit)
            self.assertEqual(result.returncode, 0)
            verify = base / "verify"
            run(base, "clone", "-q", str(remote), str(verify))
            self.assertEqual(git(verify, "rev-parse", "refs/remotes/origin/main"), source_commit)
            self.assertEqual(git(verify, "rev-parse", "refs/remotes/origin/main^{tree}"), source_tree)

    def test_concurrent_remote_move_causes_lease_failure_without_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            remote, bundle, bundle_ref, base_commit, source_commit, source_tree, trigger_commit = self.fixture(base)
            concurrent = base / "concurrent"
            run(base, "clone", "-q", str(remote), str(concurrent))
            configure(concurrent)
            run(concurrent, "checkout", "-q", "-b", "main", trigger_commit)
            (concurrent / "concurrent.txt").write_text("do not overwrite\n")
            run(concurrent, "add", ".")
            run(concurrent, "commit", "-qm", "concurrent move")
            concurrent_commit = git(concurrent, "rev-parse", "HEAD")
            run(concurrent, "push", "-q", "origin", "main")

            importer = base / "importer"
            run(base, "clone", "-q", str(remote), str(importer))
            configure(importer)
            staging_ref = "refs/codex-loop/publish"
            run(importer, "fetch", str(bundle), f"{bundle_ref}:{staging_ref}")
            result = run(
                importer,
                "push",
                f"--force-with-lease=refs/heads/main:{trigger_commit}",
                "origin",
                f"{source_commit}:refs/heads/main",
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(git(importer, "ls-remote", "origin", "refs/heads/main").split()[0], concurrent_commit)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.codex_loop as cli


class WebPublishCliDefaultTests(unittest.TestCase):
    def _run(self, *extra):
        argv = [
            "web-publish-plan",
            "--session-id", "r_test",
            "--repository", "owner/repo",
            "--branch", "main",
            "--remote-head", "1" * 40,
            "--remote-tree", "2" * 40,
            "--capability-scope", "github_push=repo:owner/repo",
            *extra,
        ]
        with patch.object(cli, "_scope_from_argv", return_value=(Path("."), Path("."), object())), \
             patch.object(cli, "web_publish_plan", return_value={"mode": "TEST"}) as planner, \
             patch.object(cli, "emit_ok"):
            rc = cli._cmd_web_publish_plan(argv)
        self.assertEqual(rc, 0)
        return planner.call_args.kwargs

    def test_fast_publish_is_cli_default_without_flag(self):
        kwargs = self._run()
        self.assertTrue(kwargs["verified_tree_fast_path"])

    def test_standard_web_requires_explicit_flag(self):
        kwargs = self._run("--standard-web")
        self.assertFalse(kwargs["verified_tree_fast_path"])

    def test_legacy_fast_flag_remains_compatible(self):
        kwargs = self._run("--verified-tree-fast-path")
        self.assertTrue(kwargs["verified_tree_fast_path"])


if __name__ == "__main__":
    unittest.main()

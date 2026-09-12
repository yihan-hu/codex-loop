#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

CLI = Path(__file__).with_name("codex_loop.py")


def run(*args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(CLI), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(proc.stdout)
    assert payload.get("ok") is True, payload
    return payload["data"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="codex-loop-smoke-") as raw:
        repo = Path(raw)
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "smoke@example.com")
        git(repo, "config", "user.name", "Codex Loop Smoke")
        (repo / "sample.txt").write_text("hello\n", encoding="utf-8")
        (repo / "AGENTS.md").write_text("root instruction\n", encoding="utf-8")
        nested = repo / "nested"
        nested.mkdir()
        (nested / "AGENTS.override.md").write_text("nested instruction\n", encoding="utf-8")
        git(repo, "add", "sample.txt", "AGENTS.md", "nested/AGENTS.override.md")
        git(repo, "commit", "-qm", "init")

        (repo / "sample.txt").write_text("user work\n", encoding="utf-8")
        orient = run(
            "orient", "--cwd", str(nested),
            "--request-anchor", "Inspect only the requested sample behavior.",
        )
        assert orient["request_anchor"] == "Inspect only the requested sample behavior."
        assert [item["contents"] for item in orient["instructions"]] == [
            "root instruction\n", "nested instruction\n"
        ]
        assert "sample.txt" in orient["preexisting_work"]["protected_paths"]
        assert orient["preexisting_work"]["safe_to_mutate"] is True
        instructions = run("instructions", "--cwd", str(nested))
        assert [item["contents"] for item in instructions] == [
            "root instruction\n", "nested instruction\n"
        ]

        run(
            "bootstrap", "--cwd", str(repo),
            "--request-anchor", "Inspect the sample repository.",
            "--objective", "Inspect sample repository",
            "--criterion", "sample.txt remains valid text",
        )
        assert run("completion", "--cwd", str(repo))["status"] == "PASS"

        run(
            "plan", "--cwd", str(repo), "--plan-json",
            '[{"step":"Inspect sample","status":"in_progress"}]',
        )
        assert run("completion", "--cwd", str(repo))["status"] == "CONTINUE"
        run(
            "plan", "--cwd", str(repo), "--plan-json",
            '[{"step":"Inspect sample","status":"completed"}]',
        )
        assert run("completion", "--cwd", str(repo))["status"] == "PASS"

        run(
            "bootstrap", "--cwd", str(repo),
            "--request-anchor", "Verify the sample repository.",
            "--objective", "Verify sample repository",
            "--criterion", "sample.txt exists",
            "--require-validation",
        )
        assert run("completion", "--cwd", str(repo))["status"] == "CONTINUE"
        check = [sys.executable, "-c", "from pathlib import Path; assert Path('sample.txt').exists()"]
        subprocess.run(check, cwd=repo, check=True)
        run(
            "validation-record", "--cwd", str(repo),
            "--command-json", json.dumps(check),
            "--exit-code", "0", "--evidence", "sample.txt existence check passed",
        )
        assert run("completion", "--cwd", str(repo))["status"] == "PASS"

        run("steer", "--cwd", str(repo), "--text", "Keep the file newline-terminated.")
        next_view = run("next", "--cwd", str(repo))
        assert next_view["request"]["steers"] == ["Keep the file newline-terminated."]

        exported = run(
            "persistence-export", "--cwd", str(repo),
            "--backend", "google_drive", "--repository", "smoke/repo",
        )
        manifest = Path(exported["manifest_path"])
        assert run("persistence-validate", "--manifest", str(manifest))["schema_version"] == 4
        resume_plan = run("persistence-resume-plan", "--manifest", str(manifest))
        assert resume_plan["freshness_rules"]["validation"] == "HISTORICAL"

        observations = repo / "resume-observations.json"
        observations.write_text(json.dumps({
            "workspace_presence": True,
            "repository_head": git(repo, "rev-parse", "HEAD"),
            "repository_tree": git(repo, "rev-parse", "HEAD^{tree}"),
            "external_actions": [],
        }), encoding="utf-8")
        resumed = run(
            "persistence-resume", "--cwd", str(repo),
            "--manifest", str(manifest), "--observations-json", str(observations),
        )
        assert resumed["status"] == "RESUMED"
        resumed_view = run("next", "--cwd", str(repo))
        assert resumed_view["request"]["steers"] == ["Keep the file newline-terminated."]
        assert resumed_view["state"]["validation"] == "missing"

    print("codex-loop smoke: PASS")


if __name__ == "__main__":
    main()

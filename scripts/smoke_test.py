#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
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
        base = Path(raw)
        runtime = base / "runtime"
        runtime.mkdir()
        os.environ["TMPDIR"] = str(runtime)
        repo = base / "repo"
        repo.mkdir()
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

        lifecycle = run("bootstrap", "--request-anchor", "Inspect only the requested sample behavior.")
        task_id = lifecycle["task_id"]
        state_path = Path(lifecycle["state"])
        assert lifecycle["workspace_bound"] is False
        assert run("completion", "--task-id", task_id)["status"] == "PASS"

        (repo / "sample.txt").write_text("user work\n", encoding="utf-8")
        orient = run("orient", "--task-id", task_id, "--cwd", str(nested))
        assert orient["task_id"] == task_id
        assert [item["contents"] for item in orient["instructions"]["entries"]] == [
            "root instruction\n", "nested instruction\n"
        ]
        assert orient["instructions"]["complete"] is True
        assert "sample.txt" in orient["preexisting_work"]["protected_paths"]
        assert orient["safe_to_mutate"] is True
        instructions = run("instructions", "--task-id", task_id, "--cwd", str(nested))
        assert [item["contents"] for item in instructions["entries"]] == [
            "root instruction\n", "nested instruction\n"
        ]

        run(
            "plan", "--task-id", task_id, "--plan-json",
            '[{"step":"Inspect sample","status":"completed"},{"step":"Finish sample","status":"in_progress"}]',
        )
        run("steer", "--task-id", task_id, "--text", "Keep the file newline-terminated.")
        next_view = run("next", "--task-id", task_id)
        assert next_view["task"]["task_id"] == task_id
        assert next_view["plan"][0]["status"] == "completed"
        assert next_view["request"]["steers"] == ["Keep the file newline-terminated."]
        assert run("authority", "--task-id", task_id)["steers"] == ["Keep the file newline-terminated."]

        run(
            "plan", "--task-id", task_id, "--plan-json",
            '[{"step":"Inspect sample","status":"completed"},{"step":"Finish sample","status":"completed"}]',
        )
        assert run("completion", "--task-id", task_id, "--cwd", str(repo))["status"] == "PASS"

        exported = run(
            "persistence-export", "--task-id", task_id, "--cwd", str(repo),
            "--backend", "google_drive", "--repository", "smoke/repo",
        )
        durable_manifest = base / "state-only.json"
        shutil.copy2(Path(exported["manifest_path"]), durable_manifest)
        shutil.rmtree(state_path.parent)

        observations = base / "resume-observations.json"
        observations.write_text(json.dumps({
            "workspace_presence": False,
            "repository_head": None,
            "repository_tree": None,
            "external_actions": [],
        }), encoding="utf-8")
        resumed = run(
            "persistence-resume", "--manifest", str(durable_manifest),
            "--observations-json", str(observations),
        )
        assert resumed["status"] == "NEEDS_RECONCILIATION"
        assert resumed["task_id"] == task_id
        resumed_view = run("next", "--task-id", task_id)
        assert resumed_view["task"]["task_id"] == task_id
        assert resumed_view["request"]["steers"] == ["Keep the file newline-terminated."]
        assert resumed_view["plan"][0]["status"] == "completed"

        rebound = run("orient", "--task-id", task_id, "--cwd", str(repo), "--rebind-verified")
        assert rebound["rebound"] is True
        assert run("next", "--task-id", task_id)["workspace_status"]["recovery_required"] is False

    print("codex-loop smoke: PASS")


if __name__ == "__main__":
    main()

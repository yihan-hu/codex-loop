from __future__ import annotations

from pathlib import Path
from typing import Any

from .shell import DetectedShell, ShellType, default_user_shell

SCRIPT_NAMES = {
    ShellType.BASH: "bash_snapshot.sh",
    ShellType.ZSH: "zsh_snapshot.sh",
    ShellType.SH: "sh_snapshot.sh",
}


def _upstream_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "upstream" / "shell_snapshot"


def capture_plan(cwd: Path, shell: DetectedShell | None = None) -> dict[str, Any]:
    """Return a host-visible capture plan; never execute startup/profile code locally."""
    shell = shell or default_user_shell()
    name = SCRIPT_NAMES.get(shell.shell_type)
    if name is None:
        if shell.shell_type in {ShellType.POWERSHELL, ShellType.CMD}:
            raise RuntimeError(f"shell snapshot is not enabled by the audited upstream Codex core for {shell.shell_type.value}; keep the bundled resource reference-only")
        raise RuntimeError(f"shell snapshot is unsupported for {shell.shell_type.value}")
    script_path = (_upstream_dir() / name).resolve()
    return {
        "requires_host_execution": True,
        "cwd": str(Path(cwd).resolve()),
        "shell_type": shell.shell_type.value,
        "shell_path": str(shell.shell_path),
        "script_path": str(script_path),
        "capture": {"login_shell": True, "timeout_seconds": 10},
        "normalize": {"start_marker": "# Snapshot file"},
        "validate": {"source_snapshot": True, "login_shell": False, "timeout_seconds": 10},
        "storage": {"private": True, "model_visible": False, "cleanup": "task_end"},
        "sensitivity": "snapshot may contain exported environment values; keep private, redact secrets, and do not load wholesale into model context",
        "reason": "shell startup/profile execution can run arbitrary user code and therefore stays host-visible",
    }

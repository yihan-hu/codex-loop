from __future__ import annotations

from pathlib import Path

from .change_tracker import sync_generation
from .process_manager import ExecResult, run_one_shot
from .state import StateStore


def validate(root: Path, cwd: Path, store: StateStore, argv: list[str], *, timeout: float | None = None) -> ExecResult:
    store.ensure_active()
    sync_generation(root, store)
    generation = store.generation()
    cwd = Path(cwd).resolve()
    result = run_one_shot(
        argv, cwd, timeout=timeout, transcript_dir=store.path.parent / "validation-transcripts"
    )
    evidence = (
        f"local runtime exit={result.exit_code}; stdout_bytes={result.stdout_total_bytes}; "
        f"stderr_bytes={result.stderr_total_bytes}; duration={result.duration_seconds:.3f}s"
    )
    store.record_validation(generation, argv, result.exit_code, cwd=cwd, source="local_runtime", evidence=evidence)
    return result

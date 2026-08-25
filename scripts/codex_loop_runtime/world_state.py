from __future__ import annotations

from pathlib import Path
from typing import Any

from codex_loop_context_projection import build_full
from .state import StateStore


def build(root: Path, cwd: Path, store: StateStore, *, reconcile: bool = True) -> dict[str, Any]:
    '''Compatibility full-state view backed by the shared context projector.'''
    return build_full(root, cwd, store, reconcile=reconcile)

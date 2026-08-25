from __future__ import annotations

from pathlib import Path
from typing import Any

from .change_tracker import sync_generation
from codex_loop_context_projection import collect_context, full_projection
from .instructions import discover
from .state import StateStore, scrub_persisted_text


def create(root: Path, cwd: Path, store: StateStore, *, key_findings: list[str] | None = None, next_action: str | None = None) -> dict[str, Any]:
    facts = collect_context(root, cwd, store, reconcile=True)
    decision = facts['decision']
    summary = full_projection(facts)
    summary.update({
        'protected_paths': sorted(store.protected_paths()),
        'baseline_git': store.get_meta('baseline_git', {}),
        'key_findings': [scrub_persisted_text(x, limit=4096) or '' for x in (key_findings or [])][:50],
        'next_action': scrub_persisted_text(next_action, limit=4096),
        'completion': {'status': decision.status.value, 'reasons': list(decision.reasons)},
    })
    store.record_checkpoint(summary)
    return summary


def restore(root: Path, cwd: Path, store: StateStore) -> dict[str, Any]:
    checkpoint = store.latest_checkpoint()
    if checkpoint is None:
        raise RuntimeError('no checkpoint exists for this task')
    changed = sync_generation(root, store)
    current_instructions = discover(cwd)
    saved = checkpoint['summary']
    saved_hashes = {str(x.get('path')): x.get('sha256') for x in saved.get('instructions', [])}
    current_hashes = {x.path: x.sha256 for x in current_instructions}
    return {
        'checkpoint': checkpoint,
        'reconciled_external_workspace_change': changed,
        'current_generation': store.generation(),
        'instruction_drift': saved_hashes != current_hashes,
        'current_instructions': [{'path': x.path, 'sha256': x.sha256, 'provenance': x.provenance} for x in current_instructions],
        'rule': 'current workspace/tool facts override stale checkpoint assumptions',
    }

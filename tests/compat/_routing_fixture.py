"""Test controller: resolve its private session profile before calling native route code."""
import json
import os
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

from scripts.codex_loop_runtime.local_connection import resolve_execution
from scripts.codex_loop_runtime.routing_state import route_init as _route_init
from scripts.codex_loop_runtime.routing_state import route_transition as _route_transition


@contextmanager
def _controller_home():
    if os.environ.get("CODEX_LOOP_PROFILE_HOME"):
        yield
    else:
        with tempfile.TemporaryDirectory() as home:
            from pathlib import Path
            profile = Path(home) / "session-profile.json"
            profile.write_text(json.dumps({"schema_version": 4}))
            profile.chmod(0o600)
            with patch.dict(os.environ, {"CODEX_LOOP_PROFILE_HOME": home}):
                yield


def _resolved(target=None, connection=None, available=None):
    with _controller_home():
        return resolve_execution(target=target, connection=connection, available_connections=available)


def route_init(**kwargs):
    target = kwargs.pop("workspace_target", None)
    connection = kwargs.pop("connection", None)
    available = kwargs.pop("available_connections", None)
    if "resolved_execution" not in kwargs:
        kwargs["resolved_execution"] = _resolved(target, connection, available)
    return _route_init(**kwargs)


def route_transition(**kwargs):
    target = kwargs.get("workspace_target")
    connection = kwargs.get("connection")
    mode = kwargs.get("workspace_mode")
    available = kwargs.pop("available_connections", None)
    if (mode or target or connection) and "resolved_execution" not in kwargs:
        kwargs["resolved_execution"] = _resolved(target or mode, connection, available)
    return _route_transition(**kwargs)

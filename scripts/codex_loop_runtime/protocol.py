from __future__ import annotations

import dataclasses
import enum
import json
from pathlib import Path
from typing import Any


class RuntimeFailure(RuntimeError):
    def __init__(self, message: str, *, code: str = "runtime_error", details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


def _safe_text(value: str) -> str:
    # JSON/SQLite cannot safely carry lone surrogate code points from POSIX filenames.
    return value.encode("utf-8", errors="replace").decode("utf-8")


def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {k: to_jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, enum.Enum):
        return to_jsonable(value.value)
    if isinstance(value, Path):
        return _safe_text(str(value))
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, dict):
        return {_safe_text(str(k)): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    return value


def emit_ok(data: Any = None) -> None:
    print(json.dumps({"ok": True, "data": to_jsonable(data)}, ensure_ascii=True, sort_keys=True))


def emit_error(exc: Exception) -> None:
    if isinstance(exc, RuntimeFailure):
        error = {"code": exc.code, "message": str(exc), "details": to_jsonable(exc.details)}
    else:
        error = {"code": "internal_error", "message": _safe_text(str(exc))}
    print(json.dumps({"ok": False, "error": error}, ensure_ascii=True, sort_keys=True))

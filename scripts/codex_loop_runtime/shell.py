from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ShellType(str, Enum):
    ZSH = "zsh"
    BASH = "bash"
    POWERSHELL = "powershell"
    SH = "sh"
    CMD = "cmd"


@dataclass(frozen=True)
class DetectedShell:
    shell_type: ShellType
    shell_path: Path


def detect_shell_type(path: str | os.PathLike[str]) -> ShellType | None:
    name = Path(path).stem.lower()
    if name == "zsh":
        return ShellType.ZSH
    if name == "bash":
        return ShellType.BASH
    if name == "sh":
        return ShellType.SH
    if name in {"pwsh", "powershell"}:
        return ShellType.POWERSHELL
    if name in {"cmd", "cmd.exe"}:
        return ShellType.CMD
    return None


def _user_shell_path() -> str | None:
    if os.name == "nt":
        return None
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_shell or None
    except Exception:
        return os.environ.get("SHELL")


def _resolve_binary(names: list[str], fallbacks: list[str]) -> Path | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    for raw in fallbacks:
        path = Path(raw)
        if path.is_file():
            return path
    return None


def get_shell(shell_type: ShellType) -> DetectedShell | None:
    user = _user_shell_path()
    if user and detect_shell_type(user) == shell_type and Path(user).is_file():
        return DetectedShell(shell_type, Path(user))
    table = {
        ShellType.ZSH: (["zsh"], ["/bin/zsh"]),
        ShellType.BASH: (["bash"], ["/bin/bash", "/usr/bin/bash"]),
        ShellType.SH: (["sh"], ["/bin/sh"]),
        ShellType.POWERSHELL: (["pwsh", "powershell"], ["/usr/local/bin/pwsh"]),
        ShellType.CMD: (["cmd"], []),
    }
    names, fallbacks = table[shell_type]
    path = _resolve_binary(names, fallbacks)
    return DetectedShell(shell_type, path) if path else None


def default_user_shell() -> DetectedShell:
    if os.name == "nt":
        return get_shell(ShellType.POWERSHELL) or DetectedShell(ShellType.CMD, Path("cmd.exe"))
    user = _user_shell_path()
    if user:
        kind = detect_shell_type(user)
        if kind:
            resolved = get_shell(kind)
            if resolved:
                return resolved
    for kind in (ShellType.BASH, ShellType.ZSH, ShellType.SH):
        resolved = get_shell(kind)
        if resolved:
            return resolved
    return DetectedShell(ShellType.SH, Path("/bin/sh"))

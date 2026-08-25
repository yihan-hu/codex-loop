from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path

SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
POWERSHELLS = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
CANONICAL_BASH_SCRIPT_PREFIX = "__codex_shell_script__"
CANONICAL_POWERSHELL_SCRIPT_PREFIX = "__codex_powershell_script__"


@dataclass(frozen=True)
class CommandIdentity:
    raw_argv: tuple[str, ...]
    canonical_argv: tuple[str, ...]
    cwd: str
    opaque: bool
    digest: str


def _basename(value: str) -> str:
    return Path(value).name.lower()


def _plain_shell_words(script: str) -> list[str] | None:
    if not script.strip():
        return None
    # Deliberately narrower than a shell parser. Any control/redirection/expansion keeps
    # the stable script identity rather than pretending to recover a simple argv.
    disallowed = ("$(", "${", "`", "<<", ">>", "&&", "||", "$", ";", "|", "&", "<", ">", "\n", "\r")
    if any(token in script for token in disallowed):
        return None
    try:
        words = shlex.split(script, posix=True)
    except ValueError:
        return None
    return words or None


def _powershell_command(words: list[str]) -> list[str] | None:
    if not words or _basename(words[0]) not in POWERSHELLS:
        return None
    for i, arg in enumerate(words[1:], start=1):
        if arg.lower() in {"-command", "-c"} and i + 1 < len(words):
            # Preserve every option/token after executable normalization. Joining tokens
            # would make semantically distinct PowerShell invocations share an identity.
            return [CANONICAL_POWERSHELL_SCRIPT_PREFIX, *words[1:]]
    return None


def canonicalize(argv: list[str] | tuple[str, ...]) -> tuple[list[str], bool]:
    words = [str(x) for x in argv]
    if not words:
        return [], False
    cmd = _basename(words[0])
    if cmd in SHELLS and len(words) >= 3 and words[1] in {"-c", "-lc"}:
        script = words[2]
        trailing = words[3:]
        # Shell arguments after the script supply $0/$1/... . Once they exist, preserve
        # them in the canonical identity even when the script itself looks word-only.
        if trailing:
            return [CANONICAL_BASH_SCRIPT_PREFIX, words[1], script, *trailing], True
        plain = _plain_shell_words(script)
        if plain is not None:
            return plain, False
        return [CANONICAL_BASH_SCRIPT_PREFIX, words[1], script], True
    ps_command = _powershell_command(words)
    if ps_command is not None:
        return ps_command, True
    return words, False


def identify(argv: list[str] | tuple[str, ...], cwd: str | Path) -> CommandIdentity:
    canonical, opaque = canonicalize(argv)
    normalized_cwd = str(Path(cwd).resolve())
    payload = {"argv": canonical, "cwd": normalized_cwd, "opaque": opaque}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return CommandIdentity(tuple(map(str, argv)), tuple(canonical), normalized_cwd, opaque, digest)


def identify_validation(argv: list[str] | tuple[str, ...], cwd: str | Path) -> CommandIdentity:
    """Exact execution identity for validation evidence.

    Approval canonicalization intentionally collapses some shell wrappers. Validation
    evidence must not: wrapper choice, exact argv token boundaries, and cwd can change
    execution semantics, so they are all part of the identity.
    """
    raw = tuple(map(str, argv))
    normalized_cwd = str(Path(cwd).resolve())
    payload = {"scheme": "validation-v2-exact-argv-cwd", "argv": list(raw), "cwd": normalized_cwd}
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return CommandIdentity(raw, raw, normalized_cwd, False, digest)

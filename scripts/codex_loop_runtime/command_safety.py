from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

MAX_WRAPPER_DEPTH = 8


class SafetyClass(str, Enum):
    SAFE_KNOWN = "safe_known"
    DANGEROUS = "dangerous"
    OPAQUE = "opaque"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SafetyAssessment:
    classification: SafetyClass
    reason: str | None = None


def _name(raw: str) -> str:
    name = Path(raw).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _rm_has_force(args: list[str]) -> bool:
    for arg in args:
        if arg == "--":
            break
        if arg == "--force":
            return True
        if arg.startswith("-") and not arg.startswith("--") and "f" in arg[1:]:
            return True
    return False


def _git_branch(args: list[str]) -> SafetyAssessment:
    mutations = {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "--edit-description", "--set-upstream-to", "-u", "--unset-upstream"}
    if any(x in mutations for x in args) or any(not x.startswith("-") for x in args):
        return SafetyAssessment(SafetyClass.DANGEROUS, "git branch mutating/positional form")
    return SafetyAssessment(SafetyClass.UNKNOWN, "Git branch remains host-visible")


def _git_tag(args: list[str]) -> SafetyAssessment:
    if any(x in {"-d", "--delete", "-a", "--annotate", "-s", "--sign", "-f", "--force"} for x in args):
        return SafetyAssessment(SafetyClass.DANGEROUS, "git tag mutating form")
    if args and not args[0].startswith("-"):
        return SafetyAssessment(SafetyClass.DANGEROUS, "git tag creation form")
    return SafetyAssessment(SafetyClass.UNKNOWN, "Git tag remains host-visible")


def _git_assessment(args: list[str]) -> SafetyAssessment:
    if len(args) == 1 and args[0] in {"--version", "-v"}:
        return SafetyAssessment(SafetyClass.SAFE_KNOWN, "pure git version query")
    if len(args) == 1 and args[0] in {"--help", "-h"}:
        return SafetyAssessment(SafetyClass.UNKNOWN, "git help may launch a viewer")
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "--no-pager":
            i += 1
            continue
        return SafetyAssessment(SafetyClass.UNKNOWN, f"git global option {args[i]!r} remains host-visible")
    if i >= len(args):
        return SafetyAssessment(SafetyClass.UNKNOWN, "Git command remains host-visible")
    sub = args[i]
    rest = args[i + 1:]
    mutating = {
        "add", "commit", "push", "reset", "clean", "checkout", "restore", "switch", "rebase", "merge",
        "cherry-pick", "revert", "rm", "mv", "stash", "am", "apply", "worktree", "update-index", "read-tree",
        "symbolic-ref", "update-ref", "fetch", "pull", "clone", "init", "gc", "repack", "maintenance",
    }
    if sub in mutating:
        return SafetyAssessment(SafetyClass.DANGEROUS, f"git {sub} can mutate repository/index/history/worktree")
    if sub == "branch":
        return _git_branch(rest)
    if sub == "tag":
        return _git_tag(rest)
    if sub == "config":
        if any(x in {"--add", "--replace-all", "--unset", "--unset-all", "--rename-section", "--remove-section", "--edit", "-e"} for x in rest):
            return SafetyAssessment(SafetyClass.DANGEROUS, "git config mutating form")
        positional = [x for x in rest if not x.startswith("-")]
        if len(positional) >= 2:
            return SafetyAssessment(SafetyClass.DANGEROUS, "git config value-setting form")
        return SafetyAssessment(SafetyClass.UNKNOWN, "git config can expose or invoke configured behavior")
    if sub == "remote" and rest and rest[0] in {"add", "remove", "rm", "rename", "set-head", "set-branches", "set-url", "update", "prune"}:
        return SafetyAssessment(SafetyClass.DANGEROUS, "git remote mutating/network form")
    return SafetyAssessment(SafetyClass.UNKNOWN, "user-requested Git commands remain host-visible; runtime probes use a separate hardened path")


def _stdin_only_filter(cmd: str, args: list[str]) -> bool:
    if cmd == "cat":
        end = False
        for arg in args:
            if end:
                if arg != "-":
                    return False
            elif arg == "--":
                end = True
            elif arg == "-":
                pass
            elif arg.startswith("-"):
                # cat flags take no filename-valued option.
                pass
            else:
                return False
        return True
    if cmd == "wc":
        safe_long = {"--bytes", "--chars", "--lines", "--max-line-length", "--words"}
        end = False
        for arg in args:
            if end:
                if arg != "-":
                    return False
            elif arg == "--":
                end = True
            elif arg == "-" or arg in safe_long:
                pass
            elif arg.startswith("--files0-from"):
                return False
            elif arg.startswith("-") and not arg.startswith("--") and set(arg[1:]) <= set("clmwL"):
                pass
            else:
                return False
        return True
    if cmd in {"head", "tail"}:
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in {"-n", "--lines", "-c", "--bytes"}:
                if i + 1 >= len(args):
                    return False
                i += 2
                continue
            if arg.startswith(("--lines=", "--bytes=")) or (arg.startswith("-") and arg[1:].isdigit()):
                i += 1
                continue
            return False
        return True
    return False


def _split_literal_script(script: str) -> list[list[str]] | None:
    if "$" in script or any(x in script for x in ("`", "\n", "\r", "if ", "then ", "for ", "while ", "case ", "trap ")):
        return None
    try:
        lexer = shlex.shlex(script, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    commands: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in {">", ">>", "<", "<<"}:
            return None
        if token in {";", "&&", "||", "|", "&"}:
            if current:
                commands.append(current)
                current = []
            continue
        # Redirection may be lexed as a token fragment in odd forms. Fail closed.
        if any(ch in token for ch in "<>"):
            return None
        current.append(token)
    if current:
        commands.append(current)
    return commands


def assess(argv: list[str] | tuple[str, ...], depth: int = 0) -> SafetyAssessment:
    words = [str(v) for v in argv]
    if depth > MAX_WRAPPER_DEPTH:
        return SafetyAssessment(SafetyClass.OPAQUE, "wrapper depth exceeded; fail closed")
    if not words:
        return SafetyAssessment(SafetyClass.UNKNOWN, "empty command")
    cmd = _name(words[0])
    if cmd == "rm" and _rm_has_force(words[1:]):
        return SafetyAssessment(SafetyClass.DANGEROUS, "forced rm")
    if cmd == "sudo":
        inner = assess(words[1:], depth + 1)
        return inner if inner.classification == SafetyClass.DANGEROUS else SafetyAssessment(SafetyClass.UNKNOWN, "sudo changes privilege context")
    if cmd == "env":
        i = 1
        while i < len(words):
            arg = words[i]
            if arg == "--":
                i += 1
                break
            if arg in {"-i", "--ignore-environment"} or ("=" in arg and not arg.startswith("-")):
                i += 1
                continue
            break
        inner = assess(words[i:], depth + 1)
        return inner if inner.classification == SafetyClass.DANGEROUS else SafetyAssessment(SafetyClass.UNKNOWN, "env changes execution context")
    if cmd in {"bash", "sh", "zsh", "dash", "ksh"} and len(words) >= 3 and words[1] in {"-c", "-lc"}:
        commands = _split_literal_script(words[2])
        if commands is not None:
            for command in commands:
                item = assess(command, depth + 1)
                if item.classification == SafetyClass.DANGEROUS:
                    return item
        return SafetyAssessment(SafetyClass.OPAQUE, "shell wrapper must remain host-visible")
    if cmd == "git":
        if "/" in words[0] or "\\" in words[0]:
            return SafetyAssessment(SafetyClass.UNKNOWN, "path-qualified executable must remain host-visible")
        return _git_assessment(words[1:])
    if "/" in words[0] or "\\" in words[0]:
        return SafetyAssessment(SafetyClass.UNKNOWN, "path-qualified executable must remain host-visible")
    if cmd in {"pwd", "true", "false", "echo", "printf", "sleep"}:
        return SafetyAssessment(SafetyClass.SAFE_KNOWN, "deterministic non-file local primitive")
    if cmd in {"cat", "head", "tail", "wc"} and _stdin_only_filter(cmd, words[1:]):
        return SafetyAssessment(SafetyClass.SAFE_KNOWN, "stdin-only filter with no file operands")
    if cmd in {"which", "type", "cat", "head", "tail", "grep", "rg", "wc", "stat", "file"}:
        return SafetyAssessment(SafetyClass.UNKNOWN, "filesystem/PATH observation stays host-visible")
    return SafetyAssessment(SafetyClass.UNKNOWN, "not classified; execute through a host-visible tool path")

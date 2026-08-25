from __future__ import annotations

import fnmatch
import os
from collections.abc import Mapping

UNIFIED_EXEC_ENV = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "LANG": "C.UTF-8",
    "LC_CTYPE": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "COLORTERM": "",
    "PAGER": "cat",
    "GIT_PAGER": "cat",
    "GH_PAGER": "cat",
    "CODEX_CI": "1",
    "GIT_TERMINAL_PROMPT": "0",
}

_NON_INHERITABLE_EXACT = {
    "CODEX_EXEC_SERVER_NOISE_AUTH_TOKEN",
    "NODE_REPL_AUTH_TOKEN",
    "OPENAI_FEDERATION_RULE_ID",
    "OPENAI_IDENTITY_TOKEN_FILE",
    "OPENAI_WORKLOAD_IDENTITY_CONTEXT",
}
_SENSITIVE_PATTERNS = ("*KEY*", "*SECRET*", "*TOKEN*", "*PASSWORD*", "*CREDENTIAL*", "*AUTHORIZATION*", "*COOKIE*")
_REPOSITORY_LOCAL_GIT_ENVIRONMENT_VARIABLES = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES", "GIT_COMMON_DIR",
    "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_DIR",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_GRAFT_FILE", "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE", "GIT_NAMESPACE", "GIT_OBJECT_DIRECTORY", "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE", "GIT_WORK_TREE",
}


def is_non_inheritable(name: str) -> bool:
    return name.upper() in _NON_INHERITABLE_EXACT


def is_sensitive_default(name: str) -> bool:
    upper = name.upper()
    return any(fnmatch.fnmatchcase(upper, pattern) for pattern in _SENSITIVE_PATTERNS)


def build_exec_env(
    base: Mapping[str, str] | None = None,
    overlay: Mapping[str, str] | None = None,
    *,
    deterministic: bool = True,
    inherit_sensitive: bool = False,
) -> dict[str, str]:
    source = dict(os.environ if base is None else base)
    source = {
        str(k): str(v) for k, v in source.items()
        if not is_non_inheritable(str(k)) and (inherit_sensitive or not is_sensitive_default(str(k)))
    }
    if overlay:
        for key, value in overlay.items():
            key = str(key)
            if is_non_inheritable(key) or (not inherit_sensitive and is_sensitive_default(key)):
                continue
            source[key] = str(value)
    if deterministic:
        # Runtime-selected deterministic settings are authoritative over both inherited
        # environment and per-call overlays.
        source.update(UNIFIED_EXEC_ENV)
    return source


def build_internal_git_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = build_exec_env(base=base)
    blocked = {item.upper() for item in _REPOSITORY_LOCAL_GIT_ENVIRONMENT_VARIABLES}
    for key in list(env):
        if key.upper() in blocked:
            env.pop(key, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_ATTR_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env

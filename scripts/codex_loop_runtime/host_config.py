from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

from .workspace_registry import host_config_path

HOST_CONFIG_SCHEMA_VERSION = 2
PROGRESS_MODES = frozenset({"quiet", "standard", "enhanced"})
BROWSER_TARGETS = frozenset({"cloud_browser", "local_chrome", "local_mac_gui"})
PERSISTENCE_BACKENDS = frozenset({"off", "google_drive"})
DEFAULT_PROGRESS_CONFIG = {"mode":"enhanced","interval_seconds":15,"tool_call_interval":3,"upfront_plan":True,"material_event_updates":True}
DEFAULT_HOST_PROFILE = {
    "schema_version": 2,
    "progress_visibility": DEFAULT_PROGRESS_CONFIG,
    "browser": {"preferred_target":"cloud_browser","allow_local_chrome_fallback":False},
    "web_publish": {"provider":"google_drive","staging_folder_id":None},
    "workspace": {"default_local_workspace":None},
    "persistence": {"task_backend":"off","host_profile_backend":"local_only"},
}
_TOP_KEYS = frozenset(DEFAULT_HOST_PROFILE)


def _check_private_regular_file(path: Path) -> None:
    info=path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode): raise RuntimeError(f"host-local Codex Loop config is not a regular file: {path}")
    if hasattr(os,"geteuid") and info.st_uid != os.geteuid(): raise PermissionError(f"host-local Codex Loop config is not owned by current user: {path}")
    if stat.S_IMODE(info.st_mode) & 0o077: raise PermissionError(f"host-local Codex Loop config permissions must be private (0600): {path}")
    if info.st_size > 256*1024: raise ValueError("host config exceeds 256 KiB")


def _ensure_private_dir(path: Path) -> Path:
    path=path.expanduser(); path = path if path.is_absolute() else path.resolve(); path.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode): raise RuntimeError(f"host-local Codex Loop path is not a real directory: {path}")
    if hasattr(os,"geteuid") and info.st_uid != os.geteuid(): raise PermissionError(f"host-local Codex Loop directory is not owned by current user: {path}")
    os.chmod(path,0o700); return path


def _atomic_json_write(path: Path, payload: dict[str,Any]) -> None:
    parent=_ensure_private_dir(path.parent)
    if path.exists() or path.is_symlink(): _check_private_regular_file(path)
    temp=path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as h:
            json.dump(payload,h,ensure_ascii=False,sort_keys=True,indent=2); h.write("\n"); h.flush(); os.fsync(h.fileno())
        os.replace(temp,path); os.chmod(path,0o600)
        try: dfd=os.open(parent,os.O_RDONLY)
        except OSError: dfd=None
        if dfd is not None:
            try: os.fsync(dfd)
            finally: os.close(dfd)
    finally:
        try: temp.unlink()
        except FileNotFoundError: pass


def _migrate_v1(raw: dict[str,Any]) -> dict[str,Any]:
    migrated=dict(raw); migrated["schema_version"]=2
    if "default_local_workspace" in migrated:
        value=migrated.pop("default_local_workspace")
        migrated.setdefault("workspace",{})["default_local_workspace"]=value
    migrated.pop("default_local_root",None)
    return migrated


def _validate_progress(raw: Any) -> dict[str,Any]:
    d=dict(DEFAULT_PROGRESS_CONFIG)
    if raw is not None:
        if not isinstance(raw,dict): raise ValueError("progress_visibility must be a JSON object")
        if set(raw)-set(d): raise ValueError("progress_visibility has unsupported keys")
        d.update(raw)
    if d["mode"] not in PROGRESS_MODES: raise ValueError("invalid progress mode")
    if isinstance(d["interval_seconds"],bool) or not isinstance(d["interval_seconds"],int) or not 5<=d["interval_seconds"]<=120: raise ValueError("progress interval out of range")
    if isinstance(d["tool_call_interval"],bool) or not isinstance(d["tool_call_interval"],int) or not 1<=d["tool_call_interval"]<=20: raise ValueError("tool call interval out of range")
    if not isinstance(d["upfront_plan"],bool) or not isinstance(d["material_event_updates"],bool): raise ValueError("progress booleans invalid")
    return d


def _validate_profile(raw: dict[str,Any]) -> dict[str,Any]:
    if set(raw)-_TOP_KEYS: raise ValueError(f"host config has unsupported top-level keys: {sorted(set(raw)-_TOP_KEYS)}")
    out=json.loads(json.dumps(DEFAULT_HOST_PROFILE)); out["schema_version"]=2
    out["progress_visibility"]=_validate_progress(raw.get("progress_visibility"))
    for section in ("browser","web_publish","workspace","persistence"):
        value=raw.get(section)
        if value is not None:
            if not isinstance(value,dict): raise ValueError(f"{section} must be an object")
            if set(value)-set(out[section]): raise ValueError(f"{section} has unsupported keys")
            out[section].update(value)
    if out["browser"]["preferred_target"] not in BROWSER_TARGETS: raise ValueError("invalid browser preferred_target")
    if not isinstance(out["browser"]["allow_local_chrome_fallback"],bool): raise ValueError("allow_local_chrome_fallback must be boolean")
    if out["web_publish"]["provider"] != "google_drive": raise ValueError("web_publish.provider must be google_drive")
    for sec,key in (("web_publish","staging_folder_id"),("workspace","default_local_workspace")):
        if out[sec][key] is not None and (not isinstance(out[sec][key],str) or not out[sec][key].strip()): raise ValueError(f"{sec}.{key} must be null or non-empty string")
    if out["persistence"]["task_backend"] not in PERSISTENCE_BACKENDS: raise ValueError("invalid task persistence backend")
    if out["persistence"]["host_profile_backend"] not in {"local_only","google_drive"}: raise ValueError("invalid host profile backend")
    return out


def _load_raw_host_config(*, strict: bool) -> tuple[dict[str,Any],list[str],bool]:
    path=host_config_path()
    try: _check_private_regular_file(path)
    except FileNotFoundError: return {"schema_version":2},[],False
    except Exception:
        if strict: raise
        return {"schema_version":2},["unsafe_host_config_ignored_for_progress"],True
    try: raw=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if strict: raise RuntimeError(f"host config is invalid and was not overwritten: {path}") from exc
        return {"schema_version":2},["invalid_host_config_json_using_progress_defaults"],True
    if not isinstance(raw,dict):
        if strict: raise ValueError("host config must be a JSON object")
        return {"schema_version":2},["invalid_host_config_using_defaults"],True
    version=raw.get("schema_version",1)
    if version==1: raw=_migrate_v1(raw)
    elif version!=2:
        if strict: raise ValueError(f"unsupported host config schema_version: {version!r}")
        return {"schema_version":2},["unsupported_host_config_version_using_defaults"],True
    return raw,[],True


def effective_host_profile() -> dict[str,Any]:
    raw,warnings,exists=_load_raw_host_config(strict=False)
    try: profile=_validate_profile(raw); source="host_file" if exists and not warnings else "default"
    except ValueError: profile=_validate_profile({"schema_version":2}); warnings=[*warnings,"invalid_host_profile_using_defaults"]; source="default"
    return {**profile,"config_path":str(host_config_path()),"config_file_exists":exists,"source":source,"warnings":warnings,"repository_persisted":False}


def _set_path(raw:dict[str,Any], path:str, value:Any, *, unset:bool=False) -> None:
    parts=path.split(".")
    if path not in {"browser.preferred_target","browser.allow_local_chrome_fallback","web_publish.staging_folder_id","workspace.default_local_workspace","persistence.task_backend","persistence.host_profile_backend"}: raise ValueError("unsupported host-config key")
    cur=raw
    for p in parts[:-1]: cur=cur.setdefault(p,{})
    if unset: cur.pop(parts[-1],None)
    else: cur[parts[-1]]=value


def set_host_config(path: str, value: Any=None, *, unset:bool=False) -> dict[str,Any]:
    raw,_,_=_load_raw_host_config(strict=True); raw=_migrate_v1(raw) if raw.get("schema_version")==1 else dict(raw); raw["schema_version"]=2
    _set_path(raw,path,value,unset=unset); normalized=_validate_profile(raw); _atomic_json_write(host_config_path(),normalized); return effective_host_profile()


def reset_host_section(section:str) -> dict[str,Any]:
    if section not in DEFAULT_HOST_PROFILE or section=="schema_version": raise ValueError("unsupported host-config section")
    raw,_,_=_load_raw_host_config(strict=True); raw=_migrate_v1(raw) if raw.get("schema_version")==1 else dict(raw); raw.pop(section,None); raw["schema_version"]=2; _atomic_json_write(host_config_path(),_validate_profile(raw)); return effective_host_profile()


def effective_progress_config() -> dict[str,Any]:
    p=effective_host_profile(); return {**p["progress_visibility"],"config_path":p["config_path"],"config_file_exists":p["config_file_exists"],"source":p["source"],"warnings":p["warnings"],"repository_persisted":False}


def set_progress_config(**kwargs:Any) -> dict[str,Any]:
    reset=bool(kwargs.pop("reset",False)); raw,_,_=_load_raw_host_config(strict=True); raw=_migrate_v1(raw) if raw.get("schema_version")==1 else dict(raw); raw["schema_version"]=2
    if reset: raw.pop("progress_visibility",None)
    else:
        cur=_validate_progress(raw.get("progress_visibility"))
        for k,v in kwargs.items():
            if v is not None: cur[k]=v
        raw["progress_visibility"]=_validate_progress(cur)
    _atomic_json_write(host_config_path(),_validate_profile(raw)); result=effective_progress_config(); result.update(saved=True,reset_to_defaults=reset); return result


def resolve_interaction_target(*, explicit_target:str|None=None, requires_user_session:bool=False) -> dict[str,Any]:
    profile=effective_host_profile(); preferred=profile["browser"]["preferred_target"]
    if explicit_target:
        target=explicit_target; reason="explicit_user_target"
    elif requires_user_session:
        target="local_chrome"; reason="task_requires_user_session"
    else:
        target=preferred; reason="host_profile_preference" if profile["source"]=="host_file" else "built_in_default"
    return {"target":target,"reason":reason,"requires_current_task_computer_use_authorization":target in {"local_chrome","local_mac_gui"},"workspace_mode_independent":True,"capability_must_be_observed":True,"silent_local_fallback":False}


def progress_policy(lifecycle_mode:str) -> dict[str,Any]:
    if lifecycle_mode not in {"direct","durable"}: raise ValueError("lifecycle_mode must be direct or durable")
    c=effective_progress_config()
    if lifecycle_mode=="direct": return {"lifecycle_mode":"direct","visibility_mode":"low_noise","periodic_updates":False,"emit_upfront_plan":False,"material_event_updates":bool(c["material_event_updates"]),"config":c,"instruction":"Keep trivial/direct work concise; do not add periodic progress messages."}
    mode=str(c["mode"])
    if mode=="quiet": return {"lifecycle_mode":"durable","visibility_mode":"quiet","periodic_updates":False,"emit_upfront_plan":False,"material_event_updates":bool(c["material_event_updates"]),"config":c,"instruction":"Suppress routine progress messages; still surface material findings or blockers when configured or required."}
    if mode=="standard": return {"lifecycle_mode":"durable","visibility_mode":"standard","periodic_updates":"host_default","emit_upfront_plan":bool(c["upfront_plan"]),"material_event_updates":bool(c["material_event_updates"]),"config":c,"instruction":"Use the host's normal progress cadence while keeping updates concise and material."}
    return {"lifecycle_mode":"durable","visibility_mode":"enhanced","periodic_updates":True,"interval_seconds":int(c["interval_seconds"]),"tool_call_interval":int(c["tool_call_interval"]),"emit_upfront_plan":bool(c["upfront_plan"]),"material_event_updates":bool(c["material_event_updates"]),"config":c,"instruction":f"Emit concise progress updates during substantive work after whichever occurs first: approximately {c['interval_seconds']} seconds or {c['tool_call_interval']} substantive tool calls; surface material findings/blockers immediately when enabled."}

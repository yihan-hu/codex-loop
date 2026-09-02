from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from .change_tracker import sync_generation
from .routing_state import permission_observation_status, route_show
from .workspace import git_head, git_status_porcelain_z, run_git

WEB_PUBLISH_CAPABILITIES = ("github_push", "github_actions", "google_drive_write")


def _sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()


def _git_text(root: Path, args: list[str]) -> str:
    proc=run_git(root,args)
    if proc.returncode != 0:
        raise RuntimeError("Git probe failed: " + proc.stderr.decode("utf-8",errors="replace").strip())
    return proc.stdout.decode("utf-8",errors="replace").strip()


def _head_tree(root: Path) -> tuple[str,str]:
    head=git_head(root)
    if not head: raise RuntimeError("Web publish requires a Git HEAD")
    return head,_git_text(root,["rev-parse",f"{head}^{{tree}}"])


def _workspace_clean(root: Path) -> bool:
    status=git_status_porcelain_z(root)
    if status is None: raise RuntimeError("cannot prove Web publish workspace cleanliness")
    return status == b""


def _validation_fresh(store: Any) -> tuple[bool,dict[str,Any]]:
    g=store.generation()
    if not bool(store.get_meta("requires_validation",True)):
        return True,{"generation":g,"reason":"task explicitly does not require validation"}
    state=store.validation_state_for_generation(g)
    ok=(int(state.get("passed_count",0))>=1 and int(state.get("failed_count",0))==0 and
        int(state.get("uncertain_count",0))==0 and int(state.get("cleanup_failed_count",0))==0 and
        int(state.get("orphaned_count",0))==0)
    return ok,{"generation":g,**state}


def _review_fresh(store: Any) -> tuple[bool,dict[str,Any]]:
    g=store.generation()
    if g==0: return True,{"generation":g,"required":False}
    reviewed=int(store.get_meta("changes_reviewed_generation",-1))==g
    return reviewed,{"generation":g,"required":True,"reviewed_generation":store.get_meta("changes_reviewed_generation",-1)}


def _current_archive_receipt(root: Path, store: Any) -> dict[str,Any] | None:
    r=store.get_meta("web_publish_archive_receipt")
    if not isinstance(r,dict): return None
    try:
        path=Path(str(r["path"])).resolve(); head,tree=_head_tree(root); size=int(r["size"]); sha=str(r["sha256"])
    except Exception: return None
    if str(r.get("source_commit"))!=head or str(r.get("source_tree"))!=tree or int(r.get("generation",-1))!=store.generation(): return None
    if not path.is_file() or path.stat().st_size!=size or _sha256_file(path)!=sha: return None
    return dict(r)


def build_web_publish_archive(root: Path, store: Any, *, output: Path, top_level: str|None=None) -> dict[str,Any]:
    root=root.resolve(); output=output.resolve(); store.ensure_active(); sync_generation(root,store)
    if not _workspace_clean(root): raise RuntimeError("publish-ready archive requires a clean workspace")
    vok,v=_validation_fresh(store); rok,r=_review_fresh(store)
    if not vok: raise RuntimeError("publish-ready archive requires fresh current-generation validation")
    if not rok: raise RuntimeError("publish-ready archive requires current-generation final change review")
    head,tree=_head_tree(root); prefix=(top_level or root.name).strip().strip("/")
    if not prefix or "/" in prefix or prefix in {".",".."}: raise ValueError("top-level archive directory must be one simple path component")
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp_name=tempfile.mkstemp(prefix=".codex-loop-publish-",suffix=".tar",dir=str(output.parent)); os.close(fd); tmp=Path(tmp_name)
    try:
        proc=run_git(root,["archive","--format=tar",f"--prefix={prefix}/",head])
        if proc.returncode!=0: raise RuntimeError("git archive failed")
        tmp.write_bytes(proc.stdout)
        with tmp.open("rb") as src, output.open("wb") as raw, gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as dst:
            for chunk in iter(lambda:src.read(1024*1024),b""): dst.write(chunk)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass
    receipt={"version":1,"generation":store.generation(),"source_commit":head,"source_tree":tree,"path":str(output),
             "size":output.stat().st_size,"sha256":_sha256_file(output),"top_level":prefix,
             "validation_generation":int(v["generation"]),"review_generation":int(r["generation"])}
    store.set_meta("web_publish_archive_receipt",receipt); return receipt


def web_publish_plan(root: Path, store: Any, *, session_id: str, repository: str, branch: str,
                     remote_head: str, remote_tree: str, capability_scopes: dict[str,str],
                     verified_tree_fast_path: bool=False) -> dict[str,Any]:
    root=root.resolve(); store.ensure_active(); sync_generation(root,store)
    route=route_show(session_id=session_id)
    if route.get("workspace_mode")!="web": raise RuntimeError("Web publish planner requires workspace_mode=web")
    for label,value in (("remote head",remote_head),("remote tree",remote_tree)):
        v=str(value).strip().lower()
        if len(v)!=40 or any(c not in "0123456789abcdef" for c in v): raise ValueError(f"{label} must be full 40-hex")
    clean=_workspace_clean(root); head,tree=_head_tree(root); vok,v=_validation_fresh(store); rok,r=_review_fresh(store)
    cap_status={}; fresh=[]; all_fresh=True
    for cap in WEB_PUBLISH_CAPABILITIES:
        scope=str(capability_scopes.get(cap) or "").strip()
        if not scope: cap_status[cap]={"fresh":False,"reason":"missing_scope"}; all_fresh=False; continue
        st=permission_observation_status(session_id=session_id,capability=cap,scope=scope); cap_status[cap]=st
        if st.get("fresh"): fresh.append(cap)
        else: all_fresh=False
    reasons=[]
    if not verified_tree_fast_path: reasons.append("verified_tree_fast_path_not_requested")
    if not clean: reasons.append("workspace_not_clean")
    if not vok: reasons.append("validation_not_fresh")
    if not rok: reasons.append("change_review_not_fresh")
    if not all_fresh: reasons.append("capability_observations_not_fresh")
    fast=not reasons; archive=_current_archive_receipt(root,store); already=str(remote_tree).lower()==tree.lower()
    return {"mode":"FAST_PUBLISH" if fast else "FULL_VERIFIED_PUBLISH","fast_path_ready":fast,"fallback_reasons":reasons,
            "repository":repository,"branch":branch,"expected_base":str(remote_head).lower(),"source_commit":head,"source_tree":tree,
            "validated_tree":tree if vok and clean else None,"validation_reused":bool(vok and clean),"review_reused":bool(rok and clean),
            "workspace_clean":clean,"capability_observations":cap_status,"capability_observations_reused":sorted(fresh),
            "archive":archive,"archive_action":"reuse" if archive else "build","already_published_by_tree":already,
            "post_push_success_requirement":"read back target branch and require remote tree == validated source tree",
            "transport":"google_drive_staging_to_audited_workspace_import",
            "next":"skip transport; continue post-push reconciliation" if already else ("stage reusable archive and run audited Workspace Import" if fast else "refresh only stale gates, then publish")}

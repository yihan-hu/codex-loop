from __future__ import annotations

from typing import Any

from .release_lineage import publish_plan
from .routing_state import route_check, route_show
from .web_publish import begin_web_publish_continuation, web_publish_plan

PUBLICATION_ROUTER_ABI = 1
SUPPORTED_CONTROLLER_ABIS = (1,)
WEB_PUBLICATION_PROTOCOL = {"name": "web_exact_git_identity", "version": 2}
LOCAL_PUBLICATION_PROTOCOL = {"name": "local_native_git", "version": 1}
WEB_PROTOCOL_REFERENCE = "references/web-mode-publish.md"
LOCAL_PROTOCOL_REFERENCE = "references/verified-native-git.md"


def _controller_contract() -> dict[str, Any]:
    return {
        "workspace_router_authoritative": True,
        "workspace_protocol_reference_authoritative": True,
        "installed_transport_instructions_must_not_override": True,
        "planner_result_is_opaque": True,
        "unmodeled_transport_forbidden": True,
        "rule": (
            "The installed/controller Skill must call this workspace-native entrypoint, read the returned "
            "workspace_protocol_reference from the current workspace before transport, and follow only the returned "
            "next_action / planner_result. Installed or remembered transport prose must not override the current workspace reference."
        ),
    }


def _unsupported_abi(controller_abi: int) -> dict[str, Any]:
    return {
        "entrypoint": "publish-enter",
        "router_abi": PUBLICATION_ROUTER_ABI,
        "accepted_controller_abis": list(SUPPORTED_CONTROLLER_ABIS),
        "controller_abi": controller_abi,
        "status": "BLOCKED",
        "code": "PUBLICATION_ROUTER_ABI_UNSUPPORTED",
        "controller_contract": _controller_contract(),
        "planner_result": None,
        "next_action": (
            "stop before publication and surface the router ABI mismatch; do not inspect GitHub object presence, "
            "search for another Web primitive, switch to Local mode, or reconstruct source through another transport"
        ),
    }


def publication_enter(
    root: Any,
    store: Any,
    *,
    session_id: str,
    repository: str,
    branch: str,
    remote_head: str,
    remote_tree: str,
    capability_scopes: dict[str, str],
    controller_abi: int = PUBLICATION_ROUTER_ABI,
    standard_web: bool = False,
    workspace_granted: bool = False,
    source_only: bool = True,
    release_id: str | None = None,
    remote: str = "origin",
) -> dict[str, Any]:
    """Stable model/controller entrypoint for repository publication.

    The installed Skill only needs to know this ABI. Publication protocol details belong
    to the current workspace runtime so a newer workspace can evolve transport behavior
    without requiring an older installed controller to rediscover that behavior in prose.
    """
    try:
        abi = int(controller_abi)
    except (TypeError, ValueError) as exc:
        raise ValueError("controller ABI must be an integer") from exc
    if abi not in SUPPORTED_CONTROLLER_ABIS:
        return _unsupported_abi(abi)

    route = route_show(session_id=session_id)
    gate = route_check(
        action="github_publish",
        session_id=session_id,
        workspace_granted=workspace_granted,
    )
    if not gate.get("allowed"):
        return {
            "entrypoint": "publish-enter",
            "router_abi": PUBLICATION_ROUTER_ABI,
            "accepted_controller_abis": list(SUPPORTED_CONTROLLER_ABIS),
            "controller_abi": abi,
            "workspace_mode": route.get("workspace_mode"),
            "status": "BLOCKED",
            "code": "PUBLICATION_ROUTE_REQUIREMENTS_UNMET",
            "requirements": list(gate.get("requirements") or []),
            "controller_contract": _controller_contract(),
            "planner_result": None,
            "next_action": (
                "satisfy only the returned routing requirements and rerun publish-enter; do not select another transport"
            ),
        }

    workspace_mode = str(route.get("workspace_mode"))
    if workspace_mode == "web":
        continuation = begin_web_publish_continuation(
            root, store, repository=repository, branch=branch
        )
        plan = web_publish_plan(
            root,
            store,
            session_id=session_id,
            repository=repository,
            branch=branch,
            remote_head=remote_head,
            remote_tree=remote_tree,
            capability_scopes=capability_scopes,
            verified_tree_fast_path=not standard_web,
        )
        return {
            "entrypoint": "publish-enter",
            "router_abi": PUBLICATION_ROUTER_ABI,
            "accepted_controller_abis": list(SUPPORTED_CONTROLLER_ABIS),
            "controller_abi": abi,
            "workspace_mode": "web",
            "publication_protocol": dict(WEB_PUBLICATION_PROTOCOL),
            "workspace_protocol_reference": WEB_PROTOCOL_REFERENCE,
            "protocol_reference_required_before_transport": True,
            "identity_contract": "remote commit == audited source commit AND remote tree == audited source tree",
            "controller_contract": _controller_contract(),
            "continuation": continuation,
            "status": str(plan.get("mode") or "PLANNED"),
            "code": "PUBLICATION_PLAN_READY",
            "planner_result": plan,
            "next_action": str(plan.get("next") or "follow planner_result exactly"),
        }

    if workspace_mode == "local":
        plan = publish_plan(
            root,
            store,
            repository=repository,
            branch=branch,
            remote_head=remote_head,
            remote_tree=remote_tree,
            remote=remote,
            release_id=release_id,
            source_only=source_only,
        )
        if plan.get("already_published"):
            next_action = "skip transport; continue post-push reconciliation"
        elif not plan.get("ready"):
            next_action = str(plan.get("reason") or "satisfy the local native-Git publish precondition and rerun publish-enter")
        else:
            next_action = (
                "execute only planner_result.git.argv through the authorized local host, then perform the required native-Git "
                "remote commit/tree readback; do not switch transport on failure"
            )
        return {
            "entrypoint": "publish-enter",
            "router_abi": PUBLICATION_ROUTER_ABI,
            "accepted_controller_abis": list(SUPPORTED_CONTROLLER_ABIS),
            "controller_abi": abi,
            "workspace_mode": "local",
            "publication_protocol": dict(LOCAL_PUBLICATION_PROTOCOL),
            "workspace_protocol_reference": LOCAL_PROTOCOL_REFERENCE,
            "protocol_reference_required_before_transport": True,
            "identity_contract": "remote commit == audited local commit AND remote tree == audited local tree",
            "controller_contract": _controller_contract(),
            "status": "LOCAL_PUBLISH_READY" if plan.get("ready") else "LOCAL_PUBLISH_BLOCKED",
            "code": "PUBLICATION_PLAN_READY",
            "planner_result": plan,
            "next_action": next_action,
        }

    return {
        "entrypoint": "publish-enter",
        "router_abi": PUBLICATION_ROUTER_ABI,
        "accepted_controller_abis": list(SUPPORTED_CONTROLLER_ABIS),
        "controller_abi": abi,
        "workspace_mode": workspace_mode,
        "status": "BLOCKED",
        "code": "PUBLICATION_WORKSPACE_MODE_UNSUPPORTED",
        "controller_contract": _controller_contract(),
        "planner_result": None,
        "next_action": "stop; do not infer a publication transport for an unknown workspace mode",
    }

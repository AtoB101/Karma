"""P2 boundary verification — enforce capability/responsibility/confirmation vs catalogs.

Security-first: counterparties and fulfill must not trust client-published
confirmation modes or incomplete merchant scopes. Verification re-derives
confirmation from human-confirmation-policy and checks scene coverage / do_not.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import AgentModel
from services.agent_boundary import (
    AgentBoundaryError,
    boundary_digest,
    canonicalize_confirmation_boundary,
    confirmation_is_looser_than_catalog,
    get_agent_boundary,
    materialize_agent_boundary,
    scene_in_do_not,
    seller_covers_scene,
)
from services.agent_onboarding_template import OnboardingError, validate_service_specs_for_industries
from services.agent_p1_readiness import boundary_content_hash, is_prod_like_env
from services.agent_profile_store import get_profile_card
from services.human_confirmation_policy import (
    allow_demo_confirmation_bypass,
    get_scene_policy,
    load_policy_catalog,
)

VERIFY_SCHEMA = "karma-agent-boundary-verify-v1"


class BoundaryVerifyError(ValueError):
    """Raised when fulfill/trade must hard-stop on boundary failure."""

    def __init__(self, message: str, *, gaps: list[str] | None = None):
        super().__init__(message)
        self.gaps = list(gaps or [])


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def verify_boundary_card(
    boundary: dict[str, Any] | None,
    *,
    agent_id: str | None = None,
    identity_class: str | None = None,
    stored_boundary_hash: str | None = None,
    require_complete: bool = True,
    scene_id: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """Verify a boundary card against catalogs (no DB)."""
    checks: dict[str, bool] = {
        "boundary_present": False,
        "schema_ok": False,
        "confirmation_catalog_aligned": False,
        "confirmation_not_looser": False,
        "capability_scenes_consistent": False,
        "service_specs_present_for_scenes": False,
        "do_not_present": False,
        "scene_covered": False,
        "scene_not_refused": False,
        "scene_policy_defined": False,
        "boundary_hash_matches_live": False,
        "boundary_complete": False,
    }
    gaps: list[str] = []
    details: dict[str, Any] = {}

    if not boundary:
        gaps.append("boundary_present")
        return _pack(
            agent_id=agent_id,
            ok=False,
            checks=checks,
            gaps=gaps,
            details=details,
            boundary=None,
            scene_id=scene_id,
        )

    checks["boundary_present"] = True
    if boundary.get("schema_version") == "karma-agent-boundary-v1":
        checks["schema_ok"] = True
    else:
        gaps.append("schema_ok")

    scenes = list(boundary.get("scene_ids") or [])
    conf = dict(boundary.get("confirmation_boundary") or {})
    conf_role = (role or conf.get("role") or "seller").lower()
    if (identity_class or boundary.get("profile_id") or "").lower() == "user":
        conf_role = "buyer"

    # Detect looser published modes vs catalog, then re-derive
    looser, looser_issues = confirmation_is_looser_than_catalog(
        conf, scene_ids=scenes, conf_role=conf_role
    )
    if looser:
        gaps.append("confirmation_not_looser")
        details["looser_issues"] = looser_issues
    else:
        checks["confirmation_not_looser"] = True

    try:
        canon = canonicalize_confirmation_boundary(
            {**boundary, "confirmation_boundary": conf},
            reject_looser=False,
        )
        checks["confirmation_catalog_aligned"] = True
        details["canonical_confirmation"] = canon.get("confirmation_boundary")
    except AgentBoundaryError as exc:
        gaps.append("confirmation_catalog_aligned")
        details["confirmation_error"] = str(exc)

    # Capability consistency
    cap = boundary.get("capability_boundary") or {}
    specs = dict(cap.get("service_specs") or {})
    conf_scenes = set(conf.get("scene_ids") or [])
    if not scenes or set(scenes) >= conf_scenes or not conf_scenes:
        checks["capability_scenes_consistent"] = True
    else:
        gaps.append("capability_scenes_consistent")
        details["orphan_confirmation_scenes"] = sorted(conf_scenes - set(scenes))

    ic = (identity_class or boundary.get("profile_id") or "").lower()
    if ic in {"merchant", "enterprise"} or conf_role == "seller":
        if scenes and all(s in specs for s in scenes):
            checks["service_specs_present_for_scenes"] = True
        elif ic == "user" or conf_role == "buyer":
            checks["service_specs_present_for_scenes"] = True
        else:
            gaps.append("service_specs_present_for_scenes")
        if str(cap.get("do_not") or "").strip():
            checks["do_not_present"] = True
        elif ic == "user" or conf_role == "buyer":
            checks["do_not_present"] = True
        else:
            gaps.append("do_not_present")
        # Soft-validate specs shape when industries known
        if scenes and specs:
            try:
                validate_service_specs_for_industries(scenes, specs)
                details["service_specs_valid"] = True
            except OnboardingError as exc:
                details["service_specs_valid"] = False
                details["service_specs_error"] = str(exc)
                if is_prod_like_env() or not allow_demo_confirmation_bypass():
                    gaps.append("service_specs_valid")
    else:
        checks["service_specs_present_for_scenes"] = True
        checks["do_not_present"] = True

    if require_complete:
        if boundary.get("boundary_complete"):
            checks["boundary_complete"] = True
        else:
            gaps.append("boundary_complete")
            details["completeness_gaps"] = boundary.get("completeness_gaps")
    else:
        checks["boundary_complete"] = bool(boundary.get("boundary_complete"))

    live_hash = boundary_content_hash(boundary)
    details["live_boundary_hash"] = live_hash
    details["stored_boundary_hash"] = stored_boundary_hash
    if stored_boundary_hash and live_hash and stored_boundary_hash == live_hash:
        checks["boundary_hash_matches_live"] = True
    elif not stored_boundary_hash:
        # Hash binding is P1's job; verify focuses on catalog alignment
        checks["boundary_hash_matches_live"] = True
    else:
        gaps.append("boundary_hash_matches_live")
        details["hash_mismatch"] = True

    # Scene-specific gates for fulfill
    if scene_id:
        policy = get_scene_policy(scene_id)
        if policy.get("fallback"):
            gaps.append("scene_policy_defined")
            details["scene_fallback"] = True
        else:
            checks["scene_policy_defined"] = True
            if policy.get("high_risk"):
                details["high_risk_scene"] = True
        if conf_role == "buyer" or ic == "user":
            checks["scene_covered"] = True
            checks["scene_not_refused"] = True
        else:
            if seller_covers_scene(boundary, scene_id):
                checks["scene_covered"] = True
            else:
                gaps.append("scene_covered")
            if scene_in_do_not(boundary, scene_id):
                gaps.append("scene_not_refused")
                details["refused_by_do_not"] = True
            else:
                checks["scene_not_refused"] = True
    else:
        # No scene asked — only require catalog scenes exist in policy
        cat_scenes = set((load_policy_catalog().get("scenes") or {}).keys())
        unknown = [s for s in scenes if s not in cat_scenes]
        if unknown:
            gaps.append("scene_policy_defined")
            details["unknown_scenes"] = unknown
        else:
            checks["scene_policy_defined"] = True
        checks["scene_covered"] = True
        checks["scene_not_refused"] = True

    # Deduplicate gaps
    uniq: list[str] = []
    for g in gaps:
        if g not in uniq:
            uniq.append(g)

    ok = len(uniq) == 0 and checks["boundary_present"] and checks["confirmation_not_looser"]
    return _pack(
        agent_id=agent_id or boundary.get("agent_id"),
        ok=ok,
        checks=checks,
        gaps=uniq,
        details=details,
        boundary=boundary,
        scene_id=scene_id,
    )


async def verify_agent_boundary(
    db: AsyncSession,
    agent_id: str,
    *,
    scene_id: str | None = None,
    require_complete: bool | None = None,
) -> dict[str, Any]:
    """Load agent + boundary and verify against P2 catalogs."""
    row = await db.get(AgentModel, agent_id)
    if not row:
        return _pack(
            agent_id=agent_id,
            ok=False,
            checks={"directory_active": False},
            gaps=["directory_active"],
            details={},
            boundary=None,
            scene_id=scene_id,
        )

    boundary = get_agent_boundary(agent_id)
    if not boundary:
        card = get_profile_card(agent_id)
        boundary = materialize_agent_boundary(
            agent_id=agent_id,
            name=row.name,
            karma_role=row.role,
            profile_id=getattr(row, "identity_class", None)
            or (card or {}).get("profile_id"),
            capabilities=list(row.capabilities or []),
            profile_card=card,
            owner_identity_id=getattr(row, "owner_identity_id", None) or agent_id,
        )

    ic = getattr(row, "identity_class", None) or (boundary or {}).get("profile_id")
    if require_complete is None:
        require_complete = (ic or "").lower() in {"merchant", "enterprise"}

    result = verify_boundary_card(
        boundary,
        agent_id=agent_id,
        identity_class=ic,
        stored_boundary_hash=getattr(row, "boundary_hash", None),
        require_complete=bool(require_complete),
        scene_id=scene_id,
        role=None,
    )
    result["identity_class"] = ic
    result["p1_ready"] = bool(getattr(row, "p1_ready", False))
    result["owner_identity_id"] = getattr(row, "owner_identity_id", None)
    result["directory_active"] = bool(row.is_active)
    if not row.is_active:
        result["ok"] = False
        if "directory_active" not in result["gaps"]:
            result["gaps"] = ["directory_active", *result["gaps"]]
    return result


def assert_seller_boundary_for_fulfill(
    *,
    boundary: dict[str, Any] | None,
    scene_id: str,
    identity_class: str | None = None,
    p1_ready: bool = False,
    stored_boundary_hash: str | None = None,
    allow_demo_incomplete: bool | None = None,
) -> dict[str, Any]:
    """Hard gate for fulfill: seller must cover scene with catalog-aligned boundary."""
    demo = (
        allow_demo_confirmation_bypass()
        if allow_demo_incomplete is None
        else bool(allow_demo_incomplete)
    )
    if not p1_ready and not demo:
        raise BoundaryVerifyError(
            "seller is not P1-ready; refuse fulfill (security)",
            gaps=["p1_ready"],
        )

    result = verify_boundary_card(
        boundary,
        identity_class=identity_class,
        stored_boundary_hash=stored_boundary_hash,
        require_complete=not demo,
        scene_id=scene_id,
        role="seller",
    )
    # In demo, still require scene coverage + not looser + policy defined
    hard = {
        "boundary_present",
        "confirmation_not_looser",
        "scene_covered",
        "scene_not_refused",
        "scene_policy_defined",
    }
    if not demo:
        hard |= {
            "confirmation_catalog_aligned",
            "service_specs_present_for_scenes",
            "do_not_present",
            "boundary_complete",
        }
    failed = [g for g in result["gaps"] if g in hard]
    if failed or not result["checks"].get("boundary_present"):
        raise BoundaryVerifyError(
            "seller boundary failed P2 verify for scene "
            f"'{scene_id}': {', '.join(failed or result['gaps'])}",
            gaps=failed or result["gaps"],
        )
    return result


def _pack(
    *,
    agent_id: str | None,
    ok: bool,
    checks: dict[str, bool],
    gaps: list[str],
    details: dict[str, Any],
    boundary: dict[str, Any] | None,
    scene_id: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": VERIFY_SCHEMA,
        "agent_id": agent_id,
        "ok": ok,
        "scene_id": scene_id,
        "checks": checks,
        "gaps": gaps,
        "details": details,
        "boundary_digest": boundary_digest(boundary),
        "security_note_zh": (
            "确认边界以目录为准重算；禁止发布比策略更松的 must_confirm；"
            "商家仅可在声明 scene_ids/service_specs 内接单；高风险行业不得静默回落全局默认。"
        ),
        "efficiency_note_zh": (
            "边界核验通过：对端可按 must_confirm/auto_ok 高效履约。"
            if ok
            else "边界核验未通过：存在 gaps，安全优先拒绝误导或超范围成交。"
        ),
        "verified_at": _iso_now(),
    }

"""Karma Agent Onboarding Template — agent-readable auto-connect standard.

Agents (not humans) read this catalog, match their real capabilities to industry
templates, materialize a standardized connect payload, then join the directory.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "evidence-schema"
    / "agent-onboarding-template.v1.json"
)

TARGET_LABELS = {
    "consumer": "C端用户",
    "business": "B端企业",
    "agent": "其他Agent",
}


class OnboardingError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_onboarding_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"onboarding catalog missing: {CATALOG_PATH}")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "karma-agent-onboarding-v1":
        raise OnboardingError("unsupported onboarding schema_version")
    return data


def list_profiles() -> list[dict[str, Any]]:
    cat = load_onboarding_catalog()
    out = []
    for pid, p in (cat.get("profiles") or {}).items():
        out.append(
            {
                "profile_id": pid,
                "title_zh": p.get("title_zh"),
                "title_en": p.get("title_en"),
                "karma_role": p.get("karma_role"),
                "selection_burden": p.get("selection_burden"),
                "owner_choices_zh": p.get("owner_choices_zh"),
            }
        )
    return out


def get_profile(profile_id: str) -> dict[str, Any]:
    cat = load_onboarding_catalog()
    p = (cat.get("profiles") or {}).get(profile_id)
    if not p:
        raise OnboardingError(f"unknown profile_id: {profile_id}")
    return p


def list_industries(
    *,
    group: str | None = None,
    audience: str | None = None,
) -> list[dict[str, Any]]:
    cat = load_onboarding_catalog()
    rows = list(cat.get("industries") or [])
    if group:
        rows = [r for r in rows if r.get("group") == group]
    if audience:
        rows = [r for r in rows if audience in (r.get("audience") or [])]
    return rows


def get_industry(industry_id: str) -> dict[str, Any]:
    for row in list_industries():
        if row.get("industry_id") == industry_id:
            return row
    raise OnboardingError(f"unknown industry_id: {industry_id}")


def _hours_text(business_hours: Any) -> str:
    if not isinstance(business_hours, dict):
        return str(business_hours or "未声明")
    if business_hours.get("24_7"):
        tz = business_hours.get("timezone") or "UTC"
        return f"7×24 ({tz})"
    weekly = business_hours.get("weekly") or "未声明时段"
    tz = business_hours.get("timezone") or "UTC"
    return f"{weekly} ({tz})"


def _targets_text(targets: list[str]) -> str:
    return "、".join(TARGET_LABELS.get(t, t) for t in targets) or "未声明"


def _validate_answers(profile_id: str, answers: dict[str, Any]) -> list[str]:
    profile = get_profile(profile_id)
    errors: list[str] = []
    for req in profile.get("required_fields") or []:
        path = req["path"]
        val = answers.get(path)
        if val is None or val == "" or val == []:
            # defaults
            if "default" in req and path not in answers:
                answers[path] = req["default"]
                val = answers[path]
            else:
                errors.append(f"missing required field: {path}")
                continue
        if path == "industry_ids":
            if not isinstance(val, list) or not val:
                errors.append("industry_ids must be a non-empty array")
            else:
                for iid in val:
                    try:
                        get_industry(str(iid))
                    except OnboardingError:
                        errors.append(f"unknown industry_id: {iid}")
        if path == "service_targets" and isinstance(val, list):
            bad = [t for t in val if t not in TARGET_LABELS]
            if bad:
                errors.append(f"invalid service_targets: {bad}")
        if path == "enterprise_type" and "enum" in req and val not in req["enum"]:
            errors.append(f"enterprise_type must be one of {req['enum']}")
    return errors


def _compliance_checks(profile_id: str, answers: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    industries = [str(x) for x in (answers.get("industry_ids") or [])]
    flags = answers.get("compliance_flags") or {}
    if not isinstance(flags, dict):
        flags = {}
        answers["compliance_flags"] = flags
    if "financial_services" in industries and flags.get("no_fund_custody") is not True:
        errors.append("financial_services requires compliance_flags.no_fund_custody=true")
    if "healthcare_medical" in industries and flags.get("non_clinical_only") is not True:
        errors.append("healthcare_medical requires compliance_flags.non_clinical_only=true")
    if profile_id == "user":
        return errors
    # auto-set safe defaults when industries absent of sensitive ones
    if "financial_services" not in industries and "no_fund_custody" not in flags:
        flags.setdefault("no_fund_custody", True)
    if "healthcare_medical" not in industries and "non_clinical_only" not in flags:
        flags.setdefault("non_clinical_only", True)
    return errors


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _validate_service_specs(industry_ids: list[str], service_specs: Any) -> list[str]:
    """Enforce per-industry hard metrics (content/type/area/pricing/hours/SLA)."""
    errors: list[str] = []
    if not isinstance(service_specs, dict) or not service_specs:
        return ["service_specs required: map of industry_id → hard service metrics"]
    for iid in industry_ids:
        ind = get_industry(iid)
        spec = service_specs.get(iid)
        if not isinstance(spec, dict):
            errors.append(f"service_specs.{iid} missing or not an object")
            continue
        for req in ind.get("required_service_spec") or []:
            path = req.get("path")
            if not path:
                continue
            # top-level business_hours / boundaries may live at answers level OR inside spec
            val = _dig(spec, path)
            if val is None or val == "" or val == []:
                errors.append(f"service_specs.{iid}.{path} required ({req.get('description_zh') or path})")
                continue
            if req.get("const") is not None and val != req["const"]:
                errors.append(f"service_specs.{iid}.{path} must be {req['const']!r}")
            if path.endswith("currency") or "price" in path or path.endswith("fare") or path.endswith("_fee") or path.endswith("per_km") or path.endswith("per_minute") or path.endswith("unit_price") or path.endswith("rate_or_fixed") or path.endswith("base_fare") or path.endswith("amount") or "nightly_rate" in path:
                if isinstance(val, (int, float)):
                    errors.append(f"service_specs.{iid}.{path} must be decimal string, not number")
        # business_hours sanity
        hours = spec.get("business_hours")
        if isinstance(hours, dict):
            if not hours.get("timezone"):
                errors.append(f"service_specs.{iid}.business_hours.timezone required")
            if not hours.get("24_7") and not hours.get("weekly"):
                errors.append(f"service_specs.{iid}.business_hours needs 24_7 or weekly")
    # unknown keys warning as errors for strictness on declared industries only
    for key in service_specs:
        if key not in industry_ids:
            errors.append(f"service_specs contains industry not in industry_ids: {key}")
    return errors


def apply_example_service_specs(industry_ids: list[str], service_specs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fill missing industry specs from catalog examples (agent bootstrap aid)."""
    out = dict(service_specs or {})
    for iid in industry_ids:
        if iid in out and isinstance(out[iid], dict) and out[iid]:
            continue
        example = get_industry(iid).get("example_service_spec")
        if isinstance(example, dict):
            out[iid] = dict(example)
    return out


def materialize_onboarding(
    *,
    profile_id: str,
    answers: dict[str, Any],
    extra_capabilities: list[str] | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Turn profile answers into a standardized connect payload + profile card."""
    if profile_id not in {"user", "merchant", "enterprise"}:
        raise OnboardingError("profile_id must be user|merchant|enterprise")
    answers = dict(answers or {})
    profile = get_profile(profile_id)

    service_specs: dict[str, Any] = {}
    if profile_id != "user":
        industry_ids_pre = [str(x) for x in (answers.get("industry_ids") or [])]
        # Bootstrap hard metrics from catalog examples when allowed / missing
        if answers.get("use_example_service_specs") or not answers.get("service_specs"):
            answers["service_specs"] = apply_example_service_specs(
                industry_ids_pre,
                answers.get("service_specs") if isinstance(answers.get("service_specs"), dict) else None,
            )
        service_specs = dict(answers.get("service_specs") or {})
        # Derive profile-level fields from first industry hard spec when omitted
        if industry_ids_pre:
            first = service_specs.get(industry_ids_pre[0]) or {}
            if not answers.get("business_hours") and isinstance(first.get("business_hours"), dict):
                answers["business_hours"] = first["business_hours"]
            if not answers.get("service_area"):
                area = first.get("service_area")
                if isinstance(area, dict):
                    answers["service_area"] = area
                elif first.get("service_area.mode") or first.get("service_area"):
                    pass
                else:
                    # digital default for pure online industries
                    answers.setdefault("service_area", {"mode": "digital", "regions": ["global"]})
            if not answers.get("boundaries"):
                parts = []
                for iid in industry_ids_pre:
                    b = (service_specs.get(iid) or {}).get("boundaries")
                    if b:
                        parts.append(str(b))
                if parts:
                    answers["boundaries"] = "；".join(parts)

    errors = _validate_answers(profile_id, answers)
    errors.extend(_compliance_checks(profile_id, answers))
    if profile_id != "user":
        errors.extend(
            _validate_service_specs(
                [str(x) for x in (answers.get("industry_ids") or [])],
                answers.get("service_specs"),
            )
        )
    if errors:
        raise OnboardingError("; ".join(errors))
    if profile_id != "user":
        service_specs = dict(answers.get("service_specs") or {})

    caps: list[str] = []
    auto = profile.get("agent_auto_fill") or {}
    if profile_id == "user":
        caps.extend(auto.get("capabilities") or [])
        industry_ids: list[str] = list(auto.get("default_scenes_interest") or [])
        description = auto.get("description_template_zh") or "Karma 用户助手"
        service_targets = ["agent"]
        business_hours = {"24_7": True, "timezone": "UTC"}
        service_area = {"mode": "digital", "regions": [answers.get("home_region") or "global"]}
        boundaries = "不对外售卖服务；仅作为需求方代理。"
        capability_summary = "发现商家、锁定重要字段、履约结算"
        service_specs = {}
    else:
        caps.extend(auto.get("always_capabilities") or [])
        industry_ids = [str(x) for x in answers.get("industry_ids") or []]
        for iid in industry_ids:
            caps.extend(get_industry(iid).get("suggested_capabilities") or [])
        service_targets = list(answers.get("service_targets") or [])
        business_hours = answers.get("business_hours") or {"24_7": True, "timezone": "UTC"}
        service_area = answers.get("service_area") or {"mode": "digital", "regions": ["global"]}
        capability_summary = str(answers.get("capability_summary") or "").strip()
        boundaries = str(answers.get("boundaries") or "").strip()
        if not capability_summary:
            # derive from service_content across specs
            bits = []
            for iid in industry_ids:
                sc = (service_specs.get(iid) or {}).get("service_content")
                if isinstance(sc, list):
                    bits.extend(str(x) for x in sc)
            capability_summary = "、".join(bits) if bits else "见 service_specs"
        if not boundaries:
            raise OnboardingError("merchant/enterprise require boundaries (or per-industry boundaries in service_specs)")
        titles = "、".join(get_industry(i).get("title_zh") or i for i in industry_ids)
        tpl = auto.get("description_template_zh") or "{display_name}"
        description = tpl.format(
            display_name=answers.get("display_name") or "Karma Agent",
            industry_titles=titles,
            service_targets=_targets_text(service_targets),
            business_hours=_hours_text(business_hours),
            capability_summary=capability_summary,
            boundaries=boundaries,
            enterprise_type=answers.get("enterprise_type") or "org",
        )

    for c in extra_capabilities or []:
        if c and c not in caps:
            caps.append(c)
    deduped: list[str] = []
    seen: set[str] = set()
    for c in caps:
        if c and c not in seen:
            seen.add(c)
            deduped.append(c)
    caps = deduped

    role = profile.get("karma_role") or "worker"
    name = str(answers.get("display_name") or "Karma Agent").strip()
    endpoint_url = answers.get("endpoint_url")

    groups: list[str] = []
    risk_tiers: list[str] = []
    for iid in industry_ids:
        ind = get_industry(iid)
        g = ind.get("group")
        if g and g not in groups:
            groups.append(str(g))
        rt = ind.get("risk_tier")
        if rt and rt not in risk_tiers:
            risk_tiers.append(str(rt))

    profile_card = {
        "schema_version": "karma-agent-onboarding-v1",
        "profile_id": profile_id,
        "industry_ids": industry_ids if profile_id != "user" else [],
        "scenes_interest": industry_ids if profile_id == "user" else industry_ids,
        "service_targets": service_targets,
        "business_hours": business_hours,
        "service_area": service_area,
        "service_specs": service_specs,
        "description": description,
        "capability_summary": capability_summary if profile_id != "user" else capability_summary,
        "boundaries": boundaries,
        "compliance_flags": answers.get("compliance_flags") or {},
        "enterprise_type": answers.get("enterprise_type") if profile_id == "enterprise" else None,
        "trade_side": answers.get("trade_side") if profile_id == "enterprise" else None,
        "preferred_currency": answers.get("preferred_currency") or "USDC",
        "language": answers.get("language") or "zh-CN",
        "hard_metrics_note_zh": "service_specs 为接入边界硬指标；单笔成交另走 Important Fields 三方锁定",
    }

    return {
        "schema_version": "karma-agent-onboarding-v1",
        "profile_id": profile_id,
        "agent_connect": {
            "agent_id": agent_id,
            "name": name,
            "role": role,
            "endpoint_url": endpoint_url,
            "capabilities": caps,
        },
        "profile_card": profile_card,
        "discovery_hints": {
            "scene_ids": industry_ids,
            "group_tags": [g for g in groups if g],
            "risk_tiers": risk_tiers,
        },
        "next_steps_zh": [
            "POST /v1/agents/connect-from-template（或 /v1/agents/connect）写入目录",
            "其他 agent 可通过 discovery 按 capabilities / scene 发现你",
            "成交前走 Important Fields 协议抓取 + 加密三方一致",
        ],
    }


def suggest_industries_for_text(text: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Lightweight keyword match so agents can auto-pick industries from self-description."""
    blob = (text or "").lower()
    keywords = {
        "ride_hailing": ["叫车", "网约车", "打车", "ride", "taxi", "uber"],
        "hotel_booking": ["酒店", "民宿", "hotel", "住宿"],
        "food_delivery": ["外卖", "food", "delivery", "餐饮"],
        "flight_booking": ["机票", "航班", "flight", "航空"],
        "b2b_procurement": ["采购", "po", "procurement", "供应"],
        "data_api_billing": ["api", "数据调用", "meter", "计费"],
        "api_tool_call": ["mcp", "工具调用", "tool call"],
        "software_development": ["开发", "代码", "software", "编程"],
        "design_creative": ["设计", "创意", "ui", "logo"],
        "content_creation": ["文案", "翻译", "内容", "content"],
        "logistics_delivery": ["物流", "快递", "配送"],
        "manufacturing": ["制造", "代工", "工厂"],
        "education_training": ["培训", "课程", "教育"],
        "marketing_advertising": ["广告", "投放", "营销"],
        "financial_services": ["对账", "财务", "报表"],
        "healthcare_medical": ["陪诊", "医疗", "健康"],
        "real_estate_services": ["房产", "看房", "租房"],
        "consulting_advisory": ["咨询", "顾问"],
    }
    scored: list[tuple[int, dict[str, Any]]] = []
    for ind in list_industries():
        iid = ind["industry_id"]
        score = 0
        for kw in keywords.get(iid, []):
            if kw.lower() in blob or kw in (text or ""):
                score += 1
        if score:
            scored.append((score, ind))
    scored.sort(key=lambda x: (-x[0], x[1].get("industry_id") or ""))
    return [row for _, row in scored[:limit]]

"""
Karma — 选哪家服务商（配置切换，不锁死任何一家）。
"""
from __future__ import annotations

from typing import Any

from config.settings import get_settings
from services.identity_provider.base import IdentityProvider, ProviderNotConfigured

#: 允许写在 IDENTITY_PROVIDER 里的值。"none" = 不接服务商，走「本人提交 + 复核台人工核验」。
PROVIDER_NAMES = ("none", "mock", "aliyun", "tencent", "persona")


def _registry() -> dict[str, Any]:
    # 延迟导入：没装的依赖 / 没配的服务商不该影响进程启动。
    from services.identity_provider.aliyun import AliyunIdentityProvider
    from services.identity_provider.mock import MockIdentityProvider
    from services.identity_provider.persona import PersonaIdentityProvider
    from services.identity_provider.tencent import TencentIdentityProvider

    return {
        "mock": MockIdentityProvider,
        "aliyun": AliyunIdentityProvider,
        "tencent": TencentIdentityProvider,
        "persona": PersonaIdentityProvider,
    }


def configured_name(settings: Any | None = None) -> str:
    active = settings if settings is not None else get_settings()
    return (getattr(active, "identity_provider", "") or "none").strip().lower() or "none"


def resolve_provider(name: str | None = None) -> IdentityProvider:
    """拿到当前生效的服务商。没接 / 没配齐一律抛错，**绝不静默降级**。"""
    settings = get_settings()
    key = (name or configured_name(settings)).strip().lower()
    if key in ("", "none"):
        raise ProviderNotConfigured(
            409,
            "no real-name/liveness provider is configured (IDENTITY_PROVIDER=none); "
            "identity verification goes through the review queue",
        )
    factory = _registry().get(key)
    if factory is None:
        raise ProviderNotConfigured(409, f"unknown identity provider: {key}")
    provider = factory(settings)
    if not provider.is_configured():
        raise ProviderNotConfigured(
            503,
            f"identity provider {key} is not configured yet; missing: "
            + ", ".join(provider.missing_config()),
        )
    return provider


def provider_status() -> dict[str, Any]:
    """给操作台 / 运维看的现状：接了没有、能不能用、缺什么。"""
    settings = get_settings()
    key = configured_name(settings)
    status: dict[str, Any] = {
        "provider": key,
        "available": list(PROVIDER_NAMES),
        "configured": False,
        "usable": False,
        "missing": [],
        "callback_ready": bool(
            (getattr(settings, "identity_provider_public_base_url", "") or "").strip()
        ),
    }
    if key == "none":
        status["missing"] = []
        status["note"] = "未接入服务商：当前走「本人提交 + 复核台人工核验」。"
        return status
    try:
        provider = resolve_provider(key)
    except ProviderNotConfigured as exc:
        factory = _registry().get(key)
        missing = factory(settings).missing_config() if factory else []
        status["missing"] = missing
        status["note"] = exc.message
        return status
    status["configured"] = True
    status["usable"] = True
    status["supports_callback"] = provider.supports_callback()
    status["supports_pull"] = provider.supports_pull()
    return status

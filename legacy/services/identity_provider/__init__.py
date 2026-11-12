"""
Karma — 第三方实名 / 活体服务适配层。

为什么要有这一层：Karma 自己不做实名，也不做人脸比对。这一层只回答两个问题：

1. **浏览器该把材料交给谁** —— ``create_session()`` 拿到的是一次核验的入口，
   浏览器**直连服务商**（证件影像、人脸影像从本机直接进服务商），Karma 不经手。
2. **这一次核验的结论是什么** —— ``parse_callback()`` / ``fetch_result()`` 把服务商
   的结论归一化成 verified / rejected / pending，再交给主身份认证的状态机。

两条红线（和 services/identity_verification.py 一致，不许绕过）：

* 服务端**永不接收**证件 / 人脸明文。适配层不提供任何「把密文给我们、我们转交服务商」
  的接口 —— 那等于把明文收进了 Karma。
* 服务商回传的报文里可能有姓名、证件号。适配层只**白名单提取**（结论、原因码、会话号、
  风险等级），其余字段一律丢弃，库里只留原始报文的 SHA-256 指纹。

密钥填进去就能通：适配器用配置切换，不锁死任何一家。
"""
from __future__ import annotations

from services.identity_provider.base import (
    OUTCOME_PENDING,
    OUTCOME_REJECTED,
    OUTCOME_VERIFIED,
    IdentityProvider,
    ProviderDecision,
    ProviderError,
    ProviderNotConfigured,
    ProviderSignatureError,
)
from services.identity_provider.registry import (
    PROVIDER_NAMES,
    provider_status,
    resolve_provider,
)

__all__ = [
    "OUTCOME_PENDING",
    "OUTCOME_REJECTED",
    "OUTCOME_VERIFIED",
    "IdentityProvider",
    "PROVIDER_NAMES",
    "ProviderDecision",
    "ProviderError",
    "ProviderNotConfigured",
    "ProviderSignatureError",
    "provider_status",
    "resolve_provider",
]

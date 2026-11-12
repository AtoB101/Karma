"""P1-6 回归：进度回执签名必须真的验得过，不能只「非空」。

历史缺陷（2026-09-17 复核）：
    ``services/receipt_guard.validate_progress_receipt_static`` 对
    ``seller_signature`` 只做 ``.strip()`` 非空检查；全项目没有任何进度回执
    验签函数。于是「卖家签过的进度」是一句空话 —— 随便填个字符串就能过，
    而它直接决定后悔责任与部分结算的金额。

修法：``progress_receipt_signing_bytes`` 给出唯一规范载荷，
``progress_receipt_signature_acceptable`` 按「生产环境必须验签、非生产允许
占位、``runtime:`` 绑定戳只认网关来源」判定。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from config.settings import settings
from core.schemas import ProgressReceipt
from services.receipt_canonical import progress_receipt_signing_bytes
from services.receipt_guard import (
    delivery_signatures_relaxed,
    is_runtime_binding_signature,
    progress_receipt_signature_acceptable,
    verify_progress_receipt_signature,
)
from services.signing import signing_service

TASK = "task-progress-signature"
SELLER = "kid_progress_seller"

# 时间戳必须写死：ProgressReceipt.timestamp 默认取 datetime.utcnow()，而 Windows 的
# 时钟粒度是 ~15ms —— 两次构造可能落在同一格、也可能跨格，于是「同内容同载荷」的
# 断言会以约 3% 的概率假红（2026-09-17 实测 150 次跑红 4 次）。业务字段全固定，
# 这条确定性断言才是在测「规范载荷是否稳定」，而不是在测系统时钟。
FIXED_TIMESTAMP = datetime(2026, 9, 17, 0, 0, 0, tzinfo=timezone.utc)


def _base() -> ProgressReceipt:
    """一份固定的进度回执（id 与 timestamp 都固定，否则载荷每次都不同）。"""
    return ProgressReceipt(
        progress_receipt_id="pr-test-0001",
        task_id=TASK,
        seller_identity_id=SELLER,
        progress_percent=50.0,
        claimed_value_percent=50.0,
        evidence_hash="a" * 64,
        runtime_log_hash="b" * 64,
        timestamp=FIXED_TIMESTAMP,
        seller_signature="",
        validation_method="auto",
    )


def _progress(signature: str) -> ProgressReceipt:
    return _base().model_copy(update={"seller_signature": signature})


def _signed() -> ProgressReceipt:
    base = _base()
    return base.model_copy(update={"seller_signature": signing_service.sign_progress(base)})


def test_canonical_progress_payload_is_stable():
    payload = progress_receipt_signing_bytes(_base())
    assert payload.startswith(b"{") and b"progress_receipt_id" in payload
    # 同一份内容必须得到同一串字节（否则验签无意义）
    assert payload == progress_receipt_signing_bytes(_base())

    # 改一个业务字段，载荷必须变
    other = _base().model_copy(update={"progress_percent": 51.0})
    assert progress_receipt_signing_bytes(other) != payload


def test_naive_and_aware_timestamps_normalise_to_one_payload():
    """同一个时刻的不同写法必须得到同一串字节（跨实现验签的前提）。

    naive UTC、带 ``Z``/``+00:00``、以及等价的 ``+08:00`` 写法都要归一，
    否则 Agent SDK 签的字到了服务端会因为时区表示法不同而验不过。
    """
    naive = _base().model_copy(update={"timestamp": datetime(2026, 9, 17, 0, 0, 0)})
    utc_aware = _base().model_copy(
        update={"timestamp": datetime(2026, 9, 17, 0, 0, 0, tzinfo=timezone.utc)}
    )
    offset_aware = _base().model_copy(
        update={"timestamp": datetime(2026, 9, 17, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))}
    )
    assert progress_receipt_signing_bytes(naive) == progress_receipt_signing_bytes(utc_aware)
    assert progress_receipt_signing_bytes(offset_aware) == progress_receipt_signing_bytes(utc_aware)

    # 归一化不等于「忽略时间戳」：真正不同的时刻必须得到不同载荷
    later = _base().model_copy(update={"timestamp": datetime(2026, 9, 17, 0, 0, 1)})
    assert progress_receipt_signing_bytes(later) != progress_receipt_signing_bytes(utc_aware)

    # 归一化之后仍然验得过：签名方用 naive、验签方拿到 aware 也必须通过
    signed = naive.model_copy(update={"seller_signature": signing_service.sign_progress(naive)})
    assert verify_progress_receipt_signature(signed.model_copy(
        update={"timestamp": datetime(2026, 9, 17, 0, 0, 0, tzinfo=timezone.utc)}
    )) is True


def test_signature_verifies_only_for_the_real_signer():
    signed = _signed()
    assert verify_progress_receipt_signature(signed) is True

    tampered = signed.model_copy(update={"progress_percent": 99.0})
    assert verify_progress_receipt_signature(tampered) is False

    assert verify_progress_receipt_signature(_progress("sig-whatever")) is False
    assert verify_progress_receipt_signature(_progress("")) is False


def test_runtime_binding_stamp_is_recognised():
    assert is_runtime_binding_signature("runtime:AbC=") is True
    assert is_runtime_binding_signature("0xdeadbeef") is False


@pytest.mark.parametrize("env", ["production", "prod"])
def test_production_rejects_unsigned_and_placeholder_progress(monkeypatch, env):
    monkeypatch.setattr(settings, "app_env", env)
    monkeypatch.setattr(settings, "openclaw_relax_delivery_signatures", False)
    monkeypatch.setattr(settings, "progress_require_signature", True)
    assert delivery_signatures_relaxed() is False

    assert progress_receipt_signature_acceptable(_progress("")) is False
    assert progress_receipt_signature_acceptable(_progress("sig-1234")) is False
    assert progress_receipt_signature_acceptable(_progress("0xtrade_pipeline_progress")) is False

    # 伪造网关绑定戳：HTTP 直连没有可信来源，一律拒绝
    assert progress_receipt_signature_acceptable(_progress("runtime:fake")) is False
    # 真网关来源才认
    assert (
        progress_receipt_signature_acceptable(
            _progress("runtime:fake"), runtime_binding_trusted=True
        )
        is True
    )

    # 真正签过的进度可以通过
    real = _signed()
    assert progress_receipt_signature_acceptable(real) is True


def test_development_still_accepts_dev_placeholders(monkeypatch):
    """开发/联调环境保留占位签名的便利，但这不是生产行为。"""
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "openclaw_relax_delivery_signatures", False)
    monkeypatch.setattr(settings, "progress_require_signature", True)

    assert progress_receipt_signature_acceptable(_progress("sig-seller")) is True
    assert progress_receipt_signature_acceptable(_progress("")) is True
    # 即便在开发环境，真签名的错误也要被发现
    assert progress_receipt_signature_acceptable(_progress("bm90LWEtc2ln")) is False

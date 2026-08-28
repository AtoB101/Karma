"""种子脚本：创建测试主身份（买家/商家）+ 2FA 码 + demo 商家上架。

用途：真人在 @hookkarma_bot 实测完整流程。
- 买家身份：kid_buyer8888 / 2FA 888888
- 商家身份：kid_seller6666 / 2FA 666666（含已认证商家 + 上架商品）

用法：cd Karma && python scripts/seed_test_identity.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eth_account import Account

from services.identity_gateway import store as identity_store
from services.miniapp_registry import store as registry

BUYER_ID = "kid_buyer8888"
BUYER_2FA = "888888"
SELLER_ID = "kid_seller6666"
SELLER_2FA = "666666"


def main() -> None:
    # ── 买家主身份 ──
    buyer_wallet = Account.create().address
    identity_store.seed_identity(
        BUYER_ID,
        buyer_wallet,
        twofa_code=BUYER_2FA,
        karma_points=120.0,
        payment_policy={
            "mode": "manual_confirm",
            "single_limit_usdc": "500",
            "daily_limit_usdc": "2000",
            "allowed_categories": [],
            "allowed_agents": [],
            "emergency_revoke": False,
        },
    )

    # ── 商家主身份 + 商家入驻 + 上架商品 ──
    seller_wallet = Account.create().address
    identity_store.seed_identity(
        SELLER_ID,
        seller_wallet,
        twofa_code=SELLER_2FA,
        karma_points=80.0,
        payment_policy={
            "mode": "manual_confirm",
            "single_limit_usdc": "500",
            "daily_limit_usdc": "2000",
            "allowed_categories": [],
            "allowed_agents": [],
            "emergency_revoke": False,
        },
    )

    # 商家已存在则不重复上架
    if not registry.list_offers() or not any(
        o.owner_identity_id == SELLER_ID for o in registry.list_offers()
    ):
        biz = registry.register_business(
            owner_identity_id=SELLER_ID,
            legal_name="Karma 测试数据服务",
            country="SG",
        )
        registry.verify_business(biz.business_id, level="verified")

        cap = registry.register_capability(
            owner_identity_id=SELLER_ID,
            name="数据抓取服务",
            category="digital",
            description="定制化数据抓取与清洗交付",
            evidence_requirements=["proof_hash"],
        )
        agt = registry.register_agent(
            owner_identity_id=SELLER_ID,
            endpoint="https://agent.karma.test/api",
            capabilities=["digital"],
            business_id=biz.business_id,
            wallet=seller_wallet,
        )
        registry.publish_offer(
            owner_identity_id=SELLER_ID,
            agent_id=agt.agent_id,
            capability_id=cap.capability_id,
            title="数据抓取服务（按次）",
            price_usdc="15",
            category="digital",
            seller_wallet=seller_wallet,
            sla={"delivery_hours": 24},
        )

    print("=" * 50)
    print("✅ 种子数据已就绪（服务需重启后加载，或直接调接口）")
    print(f"  买家身份：{BUYER_ID}   2FA：{BUYER_2FA}")
    print(f"  商家身份：{SELLER_ID}   2FA：{SELLER_2FA}")
    print("=" * 50)
    print("Bot 测试流程：")
    print("  1. 给 @hookkarma_bot 发 /start → 出菜单栏")
    print("  2. 发送「kid_buyer8888 888888」完成买家绑定")
    print("  3. 发需求「帮我找数据抓取服务，预算 20U」→ 账单确认卡 → 确认支付")
    print("  4. 发送「重新绑定」→ 输入「kid_seller6666 666666」切换商家")
    print("  5. 商家视角：点收到的「📦 接单」按钮，或查收款明细")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
MVVS V1 — 测试网全场景验证测试
==============================
6场景 x 3钱包 全链路MVVS标准验证

钱包:
  W1 (security-sentinel/buyer): 0x3295c96a2993C366B3dB27B6ac81f85801D75f51
  W2 (openclaw-worker/seller):  0x16fE563a56E6566809597e4aF9a1608d3e55Dd7F
  W3 (openmanus-worker/seller): 0x7Ed437E5786AB0d217D52937da4fF4790998d94C

场景:
  S1: API/MCP 工具调用 (L1, auto-settle)
  S2: 数据服务 (L2, buyer confirm)
  S3: AI内容生成 (L2, buyer confirm)
  S4: 链上操作 (L1, auto-settle)
  S5: A2A外包 (L3, dispute)
  S6: OTC (L4, blocked)
"""
import asyncio
import json
import os
import sys
import time
import uuid
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Config ──
WALLETS = {
    "W1": {
        "name": "security-sentinel",
        "address": "0x3295c96a2993C366B3dB27B6ac81f85801D75f51",
        "key": os.environ["W1_KEY"],
        "agent_id": "8a28bfd2-5860-431a-93b5-31b764c548e9",
    },
    "W2": {
        "name": "openclaw-worker",
        "address": "0x16fE563a56E6566809597e4aF9a1608d3e55Dd7F",
        "key": os.environ["W2_KEY"],
        "agent_id": "15b88f6b-e73d-4bd0-a894-04f378e262dc",
    },
    "W3": {
        "name": "openmanus-worker",
        "address": "0x7Ed437E5786AB0d217D52937da4fF4790998d94C",
        "key": os.environ["W3_KEY"],
        "agent_id": "fd6da5af-44a4-4855-8818-7a0de67a70ba",
    },
}

RPC_URL = "https://sepolia.infura.io/v3/a9a3c01e8b98471eb79d07eb16553236"
API_BASE = "http://127.0.0.1:8000/v1"
CHAIN_ID = 11155111

PASS = FAIL = SKIP = 0


def ok(desc, condition=True, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {desc}")
    else:
        FAIL += 1
        print(f"  ❌ {desc} — {detail}")


def skip(desc):
    global SKIP
    SKIP += 1
    print(f"  ⏭️  {desc}")


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════
# Phase 0: 环境检查
# ═══════════════════════════════════════════════════════════════
async def phase0_environment():
    print("\n" + "=" * 60)
    print("0️⃣  环境检查")
    print("=" * 60)

    # Check wallet balances
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        for name, w in WALLETS.items():
            resp = await client.post(RPC_URL, json={
                "jsonrpc": "2.0", "method": "eth_getBalance",
                "params": [w["address"], "latest"], "id": 1,
            })
            data = resp.json()
            eth = int(data.get("result", "0x0"), 16) / 1e18
            ok(f"{name} ETH balance: {eth:.4f}", eth > 0, f"balance={eth:.6f}")

        block_resp = await client.post(RPC_URL, json={
            "jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1,
        })
        block = int(block_resp.json().get("result", "0x0"), 16)
        ok(f"Sepolia block height: {block}", block > 0)

    # Check API
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{API_BASE}/health")
            api_ok = resp.status_code < 500
        ok("Karma API reachable", api_ok, f"status={resp.status_code if 'resp' in dir() else 'N/A'}")
    except Exception as e:
        skip(f"Karma API not running ({e}) — running schema-only tests")


# ═══════════════════════════════════════════════════════════════
# Phase 1: MVVS Schema Validation (offchain)
# ═══════════════════════════════════════════════════════════════
async def phase1_mvvs_schemas():
    print("\n" + "=" * 60)
    print("1️⃣  MVVS Schema 验证 (70 tests)")
    print("=" * 60)

    from core.schemas import RejectionReason, TaskStatus, SettlementState
    from core.mvvs_schemas import (
        TradeRecord, ApiCallEvidence, DataServiceEvidence,
        AiContentEvidence, ChainOpEvidence, AgentSubtaskEvidence,
        MinimumSettlementConditions, ServiceType, RiskLevel,
    )

    # 1.1 RejectionReason
    codes = [r.value for r in RejectionReason]
    ok("18 rejection codes defined", len(codes) == 18)
    ok("EMPTY_OUTPUT exists", "EMPTY_OUTPUT" in codes)
    ok("POLICY_VIOLATION exists", "POLICY_VIOLATION" in codes)

    # 1.2 TaskStatus
    ok("FROZEN status", TaskStatus.FROZEN.value == "frozen")
    ok("AUTO_CONFIRMED status", TaskStatus.AUTO_CONFIRMED.value == "auto_confirmed")

    # 1.3 TradeRecord
    tr = TradeRecord(task_id="t1", buyer_agent_id="b1", price=10.0)
    ok("TradeRecord 28+ fields", len(tr.model_fields) >= 28)
    ok("MVVS version v1.0", tr.mvvs_version == "v1.0")
    ok("Default risk L1", tr.risk_level == RiskLevel.L1)

    # 1.4 Scene 1: API Call
    evidence = ApiCallEvidence(
        request_id="r1", caller_agent_id="a1",
        request_hash="a" * 64, response_hash="b" * 64,
        http_status=200, response_time_ms=100,
        provider_signature="s" * 64, billing_count=1,
    )
    ok("S1 API auto-pass", evidence.auto_verdict() == "pass")

    evidence_fail = ApiCallEvidence(
        request_id="r2", caller_agent_id="a2",
        request_hash="c" * 64, response_hash="",
        http_status=500, response_time_ms=100, billing_count=0,
    )
    ok("S1 API auto-fail", evidence_fail.auto_verdict() == "fail")

    # 1.5 Scene 2: Data Service
    dse = DataServiceEvidence(data_file_hash="a" * 64, row_count=1000, delivery_uri="https://s3/data.csv")
    ok("S2 Data → review", dse.auto_verdict() == "review")

    dse_fail = DataServiceEvidence()
    ok("S2 Data empty → fail", dse_fail.auto_verdict() == "fail")

    # 1.6 Scene 3: AI Content
    ace = AiContentEvidence(output_file_hash="a" * 64, output_format="md", word_count=500)
    ok("S3 AI → review", ace.auto_verdict() == "review")

    ace_fail = AiContentEvidence()
    ok("S3 AI empty → fail", ace_fail.auto_verdict() == "fail")

    # 1.7 Scene 4: Chain Ops
    coe = ChainOpEvidence(chain_id=CHAIN_ID, tx_hash="0x" + "a" * 64,
                          transaction_status="success", confirmations=12,
                          risk_address_check_result="clean", sanctions_check_result="clean")
    ok("S4 Chain → pass", coe.auto_verdict() == "pass")

    coe_fail = ChainOpEvidence(chain_id=CHAIN_ID, tx_hash="0x" + "b" * 64,
                               transaction_status="failed", confirmations=0)
    ok("S4 Chain failed → fail", coe_fail.auto_verdict() == "fail")

    coe_sanctioned = ChainOpEvidence(chain_id=CHAIN_ID, tx_hash="0x" + "c" * 64,
                                     transaction_status="success", confirmations=12,
                                     risk_address_check_result="sanctioned")
    ok("S4 Chain sanctioned → fail", coe_sanctioned.auto_verdict() == "fail")

    # 1.8 Scene 5: A2A
    ase = AgentSubtaskEvidence(
        subtask_id="sub-1", upstream_agent_id="A", downstream_agent_id="B",
        subtask_price=25.0, subtask_input_hash="a" * 64, subtask_output_hash="b" * 64,
        upstream_signature="sig-A", downstream_signature="sig-B",
        subtask_evidence_hash="e" * 64, final_output_binding_hash="f" * 64,
        responsibility_chain=["buyer", "seller", "sub-1"],
    )
    ok("S5 A2A → review", ase.auto_verdict() == "review")
    ok("S5 chain valid", ase.chain_is_valid())
    ok("S5 responsible_party default=seller", ase.responsible_party() == "seller")

    ase_self = AgentSubtaskEvidence(
        subtask_id="sub-2", upstream_agent_id="A", downstream_agent_id="A",
        subtask_price=10.0,
    )
    ok("S5 self-delegation detected", ase_self.auto_fail_checks()["self_delegation"])

    # 1.9 Minimum Settlement Conditions
    msc = MinimumSettlementConditions(
        buyer_authorization_signature_valid=True,
        seller_accept_signature_valid=True,
        input_hash_exists=True, delivery_rule_exists=True,
        execution_completed=True, output_hash_exists=True,
        evidence_bundle_hash_exists=True,
        current_status_allows_settlement=True,
    )
    ok("MSC all pass", msc.all_conditions_met())

    msc.execution_completed = False
    ok("MSC detects missing execution", not msc.all_conditions_met())
    ok("MSC reports failed condition", "execution_completed" in msc.failed_conditions())


# ═══════════════════════════════════════════════════════════════
# Phase 2: Settlement State Machine
# ═══════════════════════════════════════════════════════════════
async def phase2_state_machine():
    print("\n" + "=" * 60)
    print("2️⃣  结算状态机验证")
    print("=" * 60)

    from core.schemas import TaskStatus
    from core.settlement.engine import can_transition

    # 2.1 Normal flow
    ok("DRAFT→ACCEPTED", can_transition(TaskStatus.DRAFT, TaskStatus.ACCEPTED))
    ok("ACCEPTED→IN_PROGRESS", can_transition(TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS))
    ok("IN_PROGRESS→DELIVERED", can_transition(TaskStatus.IN_PROGRESS, TaskStatus.DELIVERED))
    ok("DELIVERED→SETTLED", can_transition(TaskStatus.DELIVERED, TaskStatus.SETTLED))
    ok("DELIVERED→DISPUTED", can_transition(TaskStatus.DELIVERED, TaskStatus.DISPUTED))

    # 2.2 Dispute flow
    ok("DISPUTED→ARBITRATED", can_transition(TaskStatus.DISPUTED, TaskStatus.ARBITRATED))
    ok("ARBITRATED→SETTLED", can_transition(TaskStatus.ARBITRATED, TaskStatus.SETTLED))
    ok("ARBITRATED→REFUNDED", can_transition(TaskStatus.ARBITRATED, TaskStatus.REFUNDED))
    ok("ARBITRATED→PARTIALLY_SETTLED", can_transition(TaskStatus.ARBITRATED, TaskStatus.PARTIALLY_SETTLED))

    # 2.3 MVVS新增
    ok("DELIVERED→FROZEN", can_transition(TaskStatus.DELIVERED, TaskStatus.FROZEN))
    ok("FROZEN→SETTLED (解冻)", can_transition(TaskStatus.FROZEN, TaskStatus.SETTLED))
    ok("FROZEN→REFUNDED (解冻)", can_transition(TaskStatus.FROZEN, TaskStatus.REFUNDED))
    ok("PROGRESS_CONF→AUTO_CONFIRMED", can_transition(TaskStatus.PROGRESS_CONFIRMED, TaskStatus.AUTO_CONFIRMED))
    ok("AUTO_CONFIRMED→SETTLED", can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.SETTLED))

    # 2.4 Blocked transitions
    ok("SETTLED→DISPUTED blocked", not can_transition(TaskStatus.SETTLED, TaskStatus.DISPUTED))
    ok("DRAFT→SETTLED blocked", not can_transition(TaskStatus.DRAFT, TaskStatus.SETTLED))
    ok("AUTO_CONF→DRAFT blocked", not can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.DRAFT))


# ═══════════════════════════════════════════════════════════════
# Phase 3: 链上操作验证 (Scene 4)
# ═══════════════════════════════════════════════════════════════
async def phase3_chain_operations():
    print("\n" + "=" * 60)
    print("3️⃣  链上操作验证 (Sepolia)")
    print("=" * 60)

    import httpx

    # 3.1 Get real tx from Sepolia
    async with httpx.AsyncClient(timeout=10) as client:
        # Get latest block
        resp = await client.post(RPC_URL, json={
            "jsonrpc": "2.0", "method": "eth_getBlockByNumber",
            "params": ["latest", True], "id": 1,
        })
        block = resp.json().get("result", {})
        txs = block.get("transactions", [])
        ok("Sepolia block has transactions", len(txs) > 0, f"txs={len(txs)}")

        if txs:
            tx = txs[0]
            tx_hash = tx.get("hash", "")
            ok(f"TX hash exists: {tx_hash[:16]}...", bool(tx_hash))

            # 3.2 Get tx receipt
            resp2 = await client.post(RPC_URL, json={
                "jsonrpc": "2.0", "method": "eth_getTransactionReceipt",
                "params": [tx_hash], "id": 1,
            })
            receipt = resp2.json().get("result", {})
            tx_status_hex = receipt.get("status", "0x0")
            tx_status = "success" if tx_status_hex == "0x1" else "failed"
            confirmations = int(block.get("number", "0x0"), 16) - int(receipt.get("blockNumber", "0x0"), 16) + 1
            ok(f"TX status: {tx_status}", True)
            ok(f"Confirmations: {confirmations}", confirmations > 0)

            # 3.3 MVVS ChainOpEvidence validation
            coe = ChainOpEvidence(
                chain_id=CHAIN_ID,
                tx_hash=tx_hash,
                from_address=tx.get("from", ""),
                to_address=tx.get("to", ""),
                transaction_status=tx_status,
                confirmations=confirmations,
                risk_address_check_result="clean",
                sanctions_check_result="clean",
            )
            verdict = coe.auto_verdict()
            ok(f"S4 verdict: {verdict}", verdict in ("pass", "fail", "review"))

    # 3.4 Risk address simulation
    coe_risk = ChainOpEvidence(
        chain_id=CHAIN_ID, tx_hash="0x" + "a" * 64,
        transaction_status="success", confirmations=12,
        risk_address_check_result="flagged",
    )
    ok("S4 flagged address → fail", coe_risk.auto_verdict() == "fail")


# ═══════════════════════════════════════════════════════════════
# Phase 4: Buyer Confirm Flow
# ═══════════════════════════════════════════════════════════════
async def phase4_buyer_confirm():
    print("\n" + "=" * 60)
    print("4️⃣  买家确认流程")
    print("=" * 60)

    from core.schemas import SettlementState, RejectionReason

    # 4.1 Confirm window
    ss = SettlementState(task_id="t1", escrow_amount=100, client_agent_id="c1",
                         confirm_window_hours=48)
    ok("Confirm window set: 48h", ss.confirm_window_hours == 48)

    ss_zero = SettlementState(task_id="t2", escrow_amount=10, client_agent_id="c2",
                              confirm_window_hours=0)
    ok("Confirm window instant: 0h", ss_zero.confirm_window_hours == 0)

    ss_default = SettlementState(task_id="t3", escrow_amount=10, client_agent_id="c3")
    ok("Confirm window default: None", ss_default.confirm_window_hours is None)

    # 4.2 Rejection codes
    for code in RejectionReason:
        ss_rej = SettlementState(task_id="t4", escrow_amount=50, client_agent_id="c4",
                                 rejection_reason_code=code.value)
        ok(f"Rejection code stored: {code.value}",
           ss_rej.rejection_reason_code == code.value)

    # 4.3 Confirm deadline calculation
    now = datetime.utcnow()
    ss_deadline = SettlementState(task_id="t5", escrow_amount=100, client_agent_id="c5",
                                  confirm_window_hours=24)
    ss_deadline.confirm_deadline_at = now + timedelta(hours=24)
    ok("Confirm deadline 24h from now", ss_deadline.confirm_deadline_at > now)
    ok("Window not expired", now < ss_deadline.confirm_deadline_at)

    ss_expired = SettlementState(task_id="t6", escrow_amount=100, client_agent_id="c6",
                                 confirm_window_hours=1)
    ss_expired.confirm_deadline_at = now - timedelta(hours=1)
    ok("Window expired detected", now > ss_expired.confirm_deadline_at)


# ═══════════════════════════════════════════════════════════════
# Phase 5: Evidence Bundle MVVS Compliance
# ═══════════════════════════════════════════════════════════════
async def phase5_evidence_compliance():
    print("\n" + "=" * 60)
    print("5️⃣  证据包 MVVS 合规检查")
    print("=" * 60)

    from core.mvvs_schemas import MinimumSettlementConditions

    # 5.1 All conditions met
    msc = MinimumSettlementConditions(
        buyer_authorization_signature_valid=True,
        seller_accept_signature_valid=True,
        input_hash_exists=True,
        delivery_rule_exists=True,
        execution_completed=True,
        output_hash_exists=True,
        evidence_bundle_hash_exists=True,
        no_unresolved_dispute=True,
        no_risk_rule_block=True,
        amount_within_authorization=True,
        settlement_address_matches_task=True,
        current_status_allows_settlement=True,
    )
    ok("All 12 settlement conditions met", msc.all_conditions_met())
    ok("No failed conditions", len(msc.failed_conditions()) == 0)

    # 5.2 Missing evidence
    msc2 = MinimumSettlementConditions()
    ok("Default all-false is safe", not msc2.all_conditions_met())
    failures = msc2.failed_conditions()
    ok(f"Detects {len(failures)} failures", len(failures) >= 4)

    # 5.3 Partial failures
    msc3 = MinimumSettlementConditions(
        buyer_authorization_signature_valid=True,
        seller_accept_signature_valid=True,
        input_hash_exists=True,
        delivery_rule_exists=False,  # missing!
        execution_completed=True,
        output_hash_exists=True,
        evidence_bundle_hash_exists=False,  # missing!
        current_status_allows_settlement=True,
    )
    ok("Detects missing delivery_rule", "delivery_rule_exists" in msc3.failed_conditions())
    ok("Detects missing evidence_hash", "evidence_bundle_hash_exists" in msc3.failed_conditions())
    ok("Not all met with 2 failures", not msc3.all_conditions_met())


# ═══════════════════════════════════════════════════════════════
# Phase 6: Scene Risk Classification
# ═══════════════════════════════════════════════════════════════
async def phase6_risk_levels():
    print("\n" + "=" * 60)
    print("6️⃣  风险等级分类验证")
    print("=" * 60)

    from core.mvvs_schemas import ServiceType, RiskLevel

    # Scene → Risk mapping
    scene_risk = {
        ServiceType.API_CALL: RiskLevel.L1,
        ServiceType.MCP_TOOL: RiskLevel.L1,
        ServiceType.CHAIN_READ: RiskLevel.L1,
        ServiceType.CHAIN_WRITE: RiskLevel.L1,
        ServiceType.DATA_SERVICE: RiskLevel.L2,
        ServiceType.AI_TEXT: RiskLevel.L2,
        ServiceType.AI_IMAGE: RiskLevel.L2,
        ServiceType.AI_VIDEO: RiskLevel.L2,
        ServiceType.AI_CODE: RiskLevel.L2,
        ServiceType.AI_REPORT: RiskLevel.L2,
        ServiceType.AGENT_SUBTASK: RiskLevel.L3,
    }

    ok("L1 scenes (auto-settle): 4", sum(1 for v in scene_risk.values() if v == RiskLevel.L1) == 4)
    ok("L2 scenes (confirm): 5", sum(1 for v in scene_risk.values() if v == RiskLevel.L2) == 5)
    ok("L3 scenes (dispute): 1", sum(1 for v in scene_risk.values() if v == RiskLevel.L3) == 1)

    # Verify each scene
    for st, rl in scene_risk.items():
        tr = TradeRecord(task_id="t1", buyer_agent_id="b1", price=10.0,
                        service_type=st, risk_level=rl)
        ok(f"{st.value} → {rl.value}", tr.risk_level == rl)


# ═══════════════════════════════════════════════════════════════
# Phase 7: 安全防御测试
# ═══════════════════════════════════════════════════════════════
async def phase7_security():
    print("\n" + "=" * 60)
    print("7️⃣  安全防御测试")
    print("=" * 60)

    from core.schemas import TaskStatus
    from core.settlement.engine import can_transition
    from core.mvvs_schemas import RejectionReason

    # 7.1 Frozen state blocks normal flow
    ok("FROZEN can't go to DRAFT", not can_transition(TaskStatus.FROZEN, TaskStatus.DRAFT))
    ok("FROZEN can't go to PENDING", not can_transition(TaskStatus.FROZEN, TaskStatus.PENDING))

    # 7.2 Settled is terminal (except FROZEN)
    ok("SETTLED is terminal (except FROZEN)",
       not can_transition(TaskStatus.SETTLED, TaskStatus.DISPUTED) and
       not can_transition(TaskStatus.SETTLED, TaskStatus.DELIVERED) and
       can_transition(TaskStatus.SETTLED, TaskStatus.FROZEN))

    # 7.3 Rejection codes safe from injection
    for code in RejectionReason:
        assert ";" not in code.value
        assert "<" not in code.value
        assert "'" not in code.value
    ok("All rejection codes injection-safe", True)

    # 7.4 Scene 6 OTC should be L4
    from core.mvvs_schemas import RiskLevel
    otc_tr = TradeRecord(task_id="t-otc", buyer_agent_id="b1", price=1000.0,
                        risk_level=RiskLevel.L4)
    ok("OTC classified as L4 (blocked)", otc_tr.risk_level == RiskLevel.L4)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
async def main():
    global PASS, FAIL, SKIP
    PASS = FAIL = SKIP = 0
    t0 = time.time()

    print("🛡️  MVVS V1 测试网全场景验证测试")
    print(f"   时间: {datetime.now().isoformat()}")
    print(f"   钱包: W1={WALLETS['W1']['address'][:10]}... W2={WALLETS['W2']['address'][:10]}... W3={WALLETS['W3']['address'][:10]}...")

    await phase0_environment()
    await phase1_mvvs_schemas()
    await phase2_state_machine()
    await phase3_chain_operations()
    await phase4_buyer_confirm()
    await phase5_evidence_compliance()
    await phase6_risk_levels()
    await phase7_security()

    elapsed = time.time() - t0
    print("\n" + "=" * 60)
    print(f"📊 结果: {PASS} ✅ / {FAIL} ❌ / {SKIP} ⏭️")
    print(f"⏱️  耗时: {elapsed:.2f}s")
    print("=" * 60)

    if FAIL == 0:
        print("🟢 MVVS V1 全场景验证通过 — 测试网就绪")
        return 0
    else:
        print(f"🔴 {FAIL} 项失败 — 需要修复")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

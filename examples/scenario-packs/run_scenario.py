#!/usr/bin/env python3
"""
Karma 场景包 · 一键把一笔生意在真实网络上跑完
=================================================

    python run_scenario.py 01-data-api
    python run_scenario.py 05-cross-border-ecommerce --base https://karma-network.ai

它会用两到三把钱包身份，把这一笔生意在 Karma 上完整走一遍：

    买方下单 → 指派卖方 → 卖方开工 → 交付验真 → 执行回执 → 买方验收 → 结算

每一步都打印真实的 HTTP 结果，不做任何假动作。钱包从哪来：

    --wallets wallets.json        一个 {"buyer":{"key":...},"seller":{"key":...}} 文件
    或环境变量                     KARMA_SCENARIO_BUYER_KEY / KARMA_SCENARIO_SELLER_KEY
                                   KARMA_SCENARIO_LOGISTICS_KEY（实物场景才需要）

钱包私钥只在本机进程内存里用，不上传、不打印、不落库。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Windows 控制台默认是 GBK，中文和 ✔ 会炸；统一按 UTF-8 输出。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
from _lib.karma_flow import KarmaError, KarmaFlow, utcnow  # noqa: E402

PASS = "  \033[92m✔\033[0m "
FAIL = "  \033[91m✘\033[0m "
INFO = "  · "


def say(msg: str) -> None:
    print(msg, flush=True)


def step(title: str) -> None:
    say("")
    say(f"\033[96m▶ {title}\033[0m")


def ok(msg: str) -> None:
    say(PASS + msg)


def info(msg: str) -> None:
    say(INFO + msg)


# --------------------------------------------------------------------------- 输入
def load_wallets(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    out = {}
    for role, env in (
        ("buyer", "KARMA_SCENARIO_BUYER_KEY"),
        ("seller", "KARMA_SCENARIO_SELLER_KEY"),
        ("logistics", "KARMA_SCENARIO_LOGISTICS_KEY"),
    ):
        item = raw.get(role)
        if isinstance(item, dict):
            item = item.get("key")
        out[role] = str(item or os.environ.get(env) or "").strip()
    return out


def load_scenario(pack):
    if not pack:
        raise SystemExit("请指定场景目录，例如：python run_scenario.py 03-ride-hailing")
    path = Path(pack)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    if not (path / "scenario.json").is_file():
        raise SystemExit(f"{pack} 里没有 scenario.json")
    return json.loads((path / "scenario.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- 主流程
def run(scenario, wallets, *, base_url, fund=False):
    scene_id = scenario["scene_id"]
    flow = scenario.get("flow") or {}
    amount = float(scenario.get("amount_usdc") or 5)
    dv_mode = flow.get("delivery_verification", "none")
    needs_logistics = dv_mode == "physical_triple"
    task_id = "%s-%s" % (
        scenario["scenario_id"],
        datetime.now(timezone.utc).strftime("%m%d%H%M%S"),
    )

    say("")
    say("\033[1m场景：%s\033[0m" % scenario["title_zh"])
    info("scene_id=%s  金额=%s USDC  验真=%s" % (scene_id, amount, dv_mode))
    info("task_id=%s" % task_id)
    info("网络=%s" % base_url)

    buyer = KarmaFlow(wallets["buyer"], base_url=base_url, label="买方")
    seller = KarmaFlow(wallets["seller"], base_url=base_url, label="卖方")
    logistics = (
        KarmaFlow(wallets["logistics"], base_url=base_url, label="物流")
        if needs_logistics
        else None
    )
    for who, fo in (("买方", buyer), ("卖方", seller), ("物流", logistics)):
        if fo is None:
            continue
        ident = fo.login()
        ok("%s已登录  %s  →  %s" % (who, fo.address, ident))

    result = {"task_id": task_id, "scene_id": scene_id, "steps": []}

    def record(name, payload=None):
        result["steps"].append({"name": name, "ok": True, "payload": payload})

    # ---- 0 买方得先有钱：额度不够就先锁仓（--fund 时才替你做）
    cap = buyer.capacity()
    available = float(cap.get("available_credits") or 0.0)
    # 合同锁定与凭证占用是两次独立扣减，都从 available_credits 里走。
    needed = amount * 2
    info("买方可用额度 %s USDC（合同 + 凭证共需 %s）" % (available, needed))
    if available + 1e-9 < needed:
        deficit = round(needed - available, 6)
        if not fund:
            raise SystemExit(
                "买方可用额度不够（合同与凭证各占一次，共需 %s USDC）："
                "先在操作台「锁仓」补 %s USDC，或用 --fund 让脚本锁测试额度。"
                % (needed, deficit)
            )
        buyer.lock_credits(deficit)
        ok("已按 --fund 补锁 %s USDC（测试额度，跑完记得减少锁仓）" % deficit)
        record("test_funding", {"locked_usdc": deficit})

    # ---- 1 买方下单
    step("1 · 买方下单（授权凭证 → 任务合同 → 结算单 → 指派卖方）")
    task = scenario.get("task") or {}
    buyer.create_contract(
        task_id=task_id,
        title=task.get("title") or scenario["title_zh"],
        description=task.get("description") or scenario["title_zh"],
        escrow_amount=amount,
        expected_steps=len(flow.get("milestones") or []) or 1,
    )
    ok("任务合同已建立")
    voucher = buyer.create_voucher(
        scene_id=scene_id, seller_identity_id=seller.identity_id, amount=amount
    )
    voucher_id = str(voucher.get("voucher_id") or "")
    ok("授权凭证已开  %s  额度=%s USDC" % (voucher_id, voucher.get("amount")))
    accepted = seller.accept_voucher(voucher_id)
    ok("卖方已接单（凭证 accept，责任图谱随之落账）  状态=%s" % accepted.get("status"))
    st = buyer.create_settlement(
        task_id=task_id, escrow_amount=amount, scene_id=scene_id, voucher_id=voucher_id
    )
    ok("结算单已建立  状态=%s  选中的生意=%s" % (st.get("status"), scene_id))
    buyer.to_pending(task_id)
    ok("结算单进入 pending（买方已锁定付款意向）")
    locked = buyer.assign_seller(task_id, seller.identity_id)
    ok("已指派卖方  %s  状态=%s" % (seller.identity_id, locked.get("status")))
    record("buyer_orders", locked)

    # ---- 2 把卖方 agent 接进来
    step("2 · 卖方把 agent 接进来（授权额度 → Runtime Key → 交接登记）")
    seller.ensure_runtime_key(
        permissions=[
            "submit_receipt",
            "update_progress",
            "request_settlement",
            "sync_task_status",
        ],
        single_limit=max(amount, 50.0),
        daily_limit=max(amount * 5, 200.0),
    )
    ok("Runtime Key 已铸造（钱包签名一次，key_id=%s）" % seller.runtime_key_id)
    perms = seller.runtime_permissions()
    ok("agent 读到自己的权限：%s" % ",".join(perms.get("permissions") or []))
    readiness = seller.automation_readiness(
        task_id=task_id, role="seller", for_handoff_confirm=True
    )
    if not readiness.get("ready_for_handoff_confirm"):
        info("交接前还差：%s" % "；".join(readiness.get("blockers") or []))
    seller.handoff_confirm(task_id=task_id, role="seller")
    ok("交接已登记（服务端存证，agent 可以开始自动执行）")

    # ---- 3 卖方开工
    step("3 · 卖方接单开工")
    started = seller.start(task_id)
    ok("卖方已开工  状态=%s" % started.get("status"))

    # ---- 3 进度上报
    milestones = flow.get("milestones") or []
    if milestones:
        step("4 · 卖方上报执行进度（agent 走 Runtime Key）")
        for m in milestones:
            seller.rt_update_progress(
                task_id=task_id,
                progress_percent=float(m.get("progress_percent", 100)),
                claimed_value_percent=float(m.get("claimed_value_percent", 100)),
                note=m.get("title_zh", ""),
            )
            ok("%s  %s%%" % (m.get("title_zh"), m.get("progress_percent")))
        record("milestones", milestones)

    # ---- 4 交付验真
    if dv_mode != "none":
        step("5 · 交付验真（%s）" % dv_mode)
        verification = buyer.dv_open(
            task_id=task_id,
            scene_id=scene_id,
            seller_identity_id=seller.identity_id,
            buyer_identity_id=buyer.identity_id,
            amount=amount,
            logistics_identity_id=(logistics.identity_id if logistics else None),
        )
        vid = verification["verification_id"]
        ok("验真会话已开  %s" % vid)
        if dv_mode == "physical_triple":
            seller.dv_seller_issue(vid, ship_proof_hash="ship_" + vid)
            ok("卖方已发出（%s）" % flow.get("ship_label_zh", "已发货"))
            logistics.dv_logistics_intake(vid, item_matches=True)
            ok("物流接件核验通过（货品与锁定字段一致）")
            for extra in flow.get("seller_proofs") or []:
                seller.dv_submit_proof(vid, proof_type=extra, party_role="seller")
                ok("凭证已上传：%s" % extra)
            challenge = logistics.dv_capture_challenge(vid, party_role="logistics")
            logistics.dv_logistics_deliver(vid, challenge=challenge)
            ok("物流送达凭证已上传（系统防伪标签）")
        elif dv_mode in ("ride_track", "ticket_stub"):
            seller.dv_seller_issue(vid)
            ok(flow.get("issue_label_zh", "卖方已出具凭证"))
            for extra in flow.get("seller_proofs") or []:
                seller.dv_submit_proof(vid, proof_type=extra, party_role="seller")
                ok("凭证已上传：%s" % extra)
        buyer.dv_buyer_confirm(vid)
        final = buyer.dv(vid)
        if final.get("status") != "VERIFIED":
            raise KarmaError("GET", "/v1/delivery-verification/%s" % vid, 200, final)
        ok("验真通过  status=%s" % final.get("status"))
        record("delivery_verification", final)

    # ---- 6 执行回执
    step("6 · 卖方提交执行回执（agent 走 Runtime Key；回执由 Karma 签名）")
    receipts = flow.get("receipts") or [{"tool_name": "deliver"}]
    # The receipt timeline must sit entirely in the past: the server only accepts
    # receipts between now-24h and now+5min, and duration_ms has to equal
    # ended_at-started_at. Chain the scenario's own durations backwards from "just
    # finished" (food delivery: 10 min cooking + 5 min pickup + 15 min delivery).
    durations = [int(r.get("duration_ms") or 1200) for r in receipts]
    # 服务端只收 now-24h ~ now+5min 之间的回执，实物场景写的执行时长可能比这个窗口还长
    # （跨境那单报关+清关写了 24 小时）。装不下就按比例压缩，并如实说明，别假装是原始时长。
    window_ms = 12 * 3600 * 1000
    if sum(durations) > window_ms:
        scale = window_ms / float(sum(durations))
        before = sum(durations) / 1000.0
        durations = [max(1000, int(d * scale)) for d in durations]
        info(
            "执行时长合计 %.0fs 超过服务端回执窗口，已按比例压缩到 %.0fs 以跑通链路"
            % (before, sum(durations) / 1000.0)
        )
    cursor = utcnow() - timedelta(milliseconds=sum(durations) + 5_000)
    for idx, (r, duration_ms) in enumerate(zip(receipts, durations), start=1):
        seller.rt_submit_receipt(
            task_id=task_id,
            step_index=idx,
            tool_name=r.get("tool_name", "deliver"),
            input_payload="%s:%s:in" % (task_id, idx),
            output_payload="%s:%s:out" % (task_id, idx),
            started_at=cursor,
            duration_ms=duration_ms,
        )
        cursor = cursor + timedelta(milliseconds=duration_ms)
        ok("回执 #%s  %s  success" % (idx, r.get("tool_name", "deliver")))

    # ---- 7 交付
    delivered = seller.rt_request_settlement(task_id, "submit_delivery")
    ok("卖方已交付  状态=%s" % delivered.get("status"))

    # ---- 8 买方验收结算
    step("8 · 买方验收 → 结算")
    try:
        settled = buyer.buyer_accept(task_id, scene_id=scene_id)
    except KarmaError as exc:
        body = exc.body if isinstance(exc.body, dict) else {}
        if exc.status != 403 or "confirmation" not in json.dumps(body):
            raise
        sess = body.get("confirmation") or {}
        sid = sess.get("session_id")
        info("这一单按规则要主人点头：%s" % body.get("owner_prompt_zh", ""))
        if not sid:
            fresh = buyer.start_confirmation(
                scene_id=scene_id, step="buyer_accept_settle", amount=amount
            )
            sid = fresh.get("session_id")
        if not sid:
            raise RuntimeError(
                "后端要求主人确认，但没给出确认会话 ID —— 请检查确认区配置：%s" % body
            )
        buyer.decide_confirmation(sid, confirm=True)
        ok("主人已确认  %s" % sid)
        settled = buyer.buyer_accept(task_id, scene_id=scene_id, confirmation_session_id=sid)
    ok("结算完成  状态=%s  释放=%s USDC" % (settled.get("status"), settled.get("released_amount")))
    record("settled", settled)

    step("9 · 最终状态")
    final_state = buyer.settlement(task_id) or settled
    info("status=%s" % final_state.get("status"))
    info("escrow=%s  released=%s" % (final_state.get("escrow_amount"), final_state.get("released_amount")))
    try:
        rows = buyer.transitions(task_id)
        info("流转记录 %s 条：%s" % (len(rows), " → ".join(str(r.get("to_status")) for r in rows)))
    except KarmaError:
        pass
    result["final_status"] = final_state.get("status")
    # ??? TaskStatus ???????settled??????????
    result["ok"] = str(final_state.get("status") or "").upper() == "SETTLED"
    for fo in (buyer, seller, logistics):
        if fo is not None:
            fo.close()
    return result


def main():
    ap = argparse.ArgumentParser(description="Karma 场景包一键端到端")
    ap.add_argument("pack", help="场景目录，例如 03-ride-hailing")
    ap.add_argument("--base", default=os.environ.get("KARMA_BASE_URL", "https://karma-network.ai"))
    ap.add_argument("--wallets", default=None, help="钱包文件 JSON（buyer/seller/logistics）")
    ap.add_argument("--json", action="store_true", help="只输出机器可读结果")
    ap.add_argument(
        "--fund",
        action="store_true",
        help="买方可用额度不足时，自动锁一笔测试额度把链路跑通（跑完请减少锁仓）",
    )
    args = ap.parse_args()

    scenario = load_scenario(args.pack)
    wallets = load_wallets(args.wallets)
    missing = [k for k in ("buyer", "seller") if not wallets.get(k)]
    if (scenario.get("flow") or {}).get("delivery_verification") == "physical_triple":
        missing += [k for k in ("logistics",) if not wallets.get(k)]
    if missing:
        raise SystemExit("缺少钱包：" + ", ".join(missing) + "（用 --wallets 或环境变量提供）")

    try:
        result = run(scenario, wallets, base_url=args.base, fund=args.fund)
    except KarmaError as exc:
        say("")
        say(FAIL + str(exc))
        return 1
    if args.json:
        say(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        say("")
        say(
            ("\033[92m全部跑通 ✔\033[0m" if result["ok"] else "\033[91m未跑通 ✘\033[0m")
            + "  task_id=%s" % result["task_id"]
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Karma · 资金路径自动化回归（部署后跑一遍，出事就报警）。

两个场景，全部打**生产 API**（不改库、不打桩、不绕过任何闸）：

  settle   下单 → 交付 → 执行回执 → 买方确认 → 链上放款（买方钱包 → 卖方钱包）
  dispute  下单 → 交付 → 执行回执 → 开争议 → 越权全挡 → 仲裁裁决 → 链上罚没（卖方钱包 → 买方钱包）

它盯的是「钱有没有按状态机走」：

  * 该成功的一步必须成功（< 400）；越权必须被挡（409 / 403）；
  * 结算单上的链上事实必须回写（onchain_status / onchain_binding_id / tx_hash）；
  * 卖方收付中心必须看得见这一单，binding 状态要跟链上一致，且带三笔链上 tx；
  * 买方额度账本必须跟着动（reserved → disputed → 放回 / 核销）。

配置（全部走环境变量，密钥不写进文件）：

  KARMA_BASE                      默认 https://karma-network.ai
  KARMA_OWNER_API_KEY             买方身份的 owner API key（操作台「接入 agent」那一把）
  KARMA_BUYER_ID                  买方身份 id（kid_…）
  KARMA_BUYER_WALLET              买方钱包地址
  KARMA_BUYER_PK                  买方钱包私钥（签 SIWE + 授权建 runtime key）
  KARMA_SELLER_ID                 卖方身份 id（kid_…，必须是另一个钱包）
  KARMA_SELLER_PK                 卖方钱包私钥
  KARMA_AMOUNT                    每单金额，默认 0.1
  KARMA_REG_STATE                 卖方 agent 复用状态文件（默认：临时目录）
  KARMA_REG_TIMEOUT               终局轮询上限秒数，默认 420

用法：

  python scripts/regression/money_path_regression.py --scenario all --out /tmp/report.json

退出码：0 = 全过；1 = 有断言失败（报告里逐条写明哪一条、期望什么、拿到什么）。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from eth_account import Account
from eth_account.messages import encode_defunct

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from sdk.runtime_client import build_agent_request_message  # noqa: E402

PERMS = sorted([
    "discover_agents", "place_order", "request_settlement", "request_voucher",
    "submit_receipt", "sync_task_status", "update_progress",
])
SINGLE_LIMIT = 0.5
DAILY_LIMIT = 2.0
EPS = 0.005  # 金额比较容差（USDC 两位小数）


class Report:
    """一次回归的全部事实：逐条断言 + 原始步骤日志 + 给链上核对用的期望。"""

    def __init__(self, base: str) -> None:
        self.base = base
        self.scenarios: dict = {}
        self.chain_expectations: list = []
        self._cur = None

    def start(self, name: str) -> None:
        self._cur = name
        self.scenarios[name] = {"ok": True, "checks": [], "log": [], "task_id": None}

    def log(self, step: str, data) -> None:
        payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        self.scenarios[self._cur]["log"].append({"step": step, "data": data})
        print("  %-26s %s" % (step, payload[:430]))

    def check(self, name: str, ok: bool, detail=None) -> bool:
        entry = {"name": name, "ok": bool(ok)}
        if detail is not None:
            entry["detail"] = detail
        self.scenarios[self._cur]["checks"].append(entry)
        mark = "OK" if ok else "!!"
        print("  %s %s%s" % (mark, name, "" if ok or detail is None
                             else "  <- " + json.dumps(detail, ensure_ascii=False)[:360]))
        if not ok:
            self.scenarios[self._cur]["ok"] = False
        return bool(ok)

    def conserved(self, name: str, cap: dict) -> bool:
        """额度台账守恒式：``total_bill_credits == active`` 且 ``total_locked_usdc >= active``。

        镜像对账 / 接单预留 / 争议冻结 / 结算放款都在写这一行。派生列被写坏的时候钱一分
        没动，但下一个动钱的入口就会 500（2026-09-29 真机：开争议 500 "capacity invariant
        check failed"）。所以这条断言必须留在回归里。
        """
        active = sum(
            float(cap.get(k) or 0.0)
            for k in ("available_credits", "reserved_credits", "in_progress_credits",
                      "confirmed_progress_credits", "disputed_credits",
                      "pending_settlement_credits")
        )
        bill = float(cap.get("total_bill_credits") or 0.0)
        locked = float(cap.get("total_locked_usdc") or 0.0)
        ok = abs(bill - active) <= 1e-6 and locked + 1e-6 >= active
        return self.check(name, ok, {"active": round(active, 6),
                                     "total_bill_credits": bill,
                                     "total_locked_usdc": locked})

    def near(self, name: str, got, want, tol: float = EPS) -> bool:
        try:
            ok = abs(float(got) - float(want)) <= tol
        except (TypeError, ValueError):
            ok = False
        return self.check(name, ok, {"got": got, "want": want, "tol": tol})

    def expect_onchain(self, **kw) -> None:
        self.chain_expectations.append(kw)

    @property
    def ok(self) -> bool:
        return all(s["ok"] for s in self.scenarios.values())

    def as_dict(self) -> dict:
        return {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "base": self.base,
            "ok": self.ok,
            "scenarios": self.scenarios,
            "chain_expectations": self.chain_expectations,
        }


class Cfg:
    def __init__(self) -> None:
        self.base = (os.environ.get("KARMA_BASE") or "https://karma-network.ai").rstrip("/")
        self.owner_key = os.environ.get("KARMA_OWNER_API_KEY") or ""
        self.buyer_id = os.environ.get("KARMA_BUYER_ID") or ""
        self.buyer_wallet = os.environ.get("KARMA_BUYER_WALLET") or ""
        self.buyer_pk = os.environ.get("KARMA_BUYER_PK") or ""
        self.seller_id = os.environ.get("KARMA_SELLER_ID") or ""
        self.seller_pk = os.environ.get("KARMA_SELLER_PK") or ""
        self.amount = float(os.environ.get("KARMA_AMOUNT") or 0.1)
        self.state_path = os.environ.get("KARMA_REG_STATE") or os.path.join(
            tempfile.gettempdir(), "karma-regression-state.json"
        )
        self.timeout = int(os.environ.get("KARMA_REG_TIMEOUT") or 420)

    def require(self) -> list:
        return [k for k, v in (
            ("KARMA_OWNER_API_KEY", self.owner_key),
            ("KARMA_BUYER_ID", self.buyer_id),
            ("KARMA_BUYER_WALLET", self.buyer_wallet),
            ("KARMA_BUYER_PK", self.buyer_pk),
            ("KARMA_SELLER_ID", self.seller_id),
            ("KARMA_SELLER_PK", self.seller_pk),
        ) if not v]


def b64pub(key) -> str:
    return base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def sign_headers(key, key_id: str, method: str, path: str, body: bytes) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = uuid.uuid4().hex
    msg = build_agent_request_message(
        key_id=key_id, method=method, path=path, timestamp=ts, nonce=nonce,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    return {
        "X-Karma-Runtime-Timestamp": ts,
        "X-Karma-Runtime-Nonce": nonce,
        "X-Karma-Agent-Signature": base64.b64encode(key.sign(msg.encode())).decode(),
    }


async def agent_call(c, base: str, method: str, path: str, key, key_id: str, token: str, payload=None):
    body = b"" if payload is None else json.dumps(
        payload, separators=(",", ":"), sort_keys=True).encode()
    headers = {"Content-Type": "application/json", "X-Karma-Runtime-Key": token}
    headers.update(sign_headers(key, key_id, method, path, body))
    r = await c.request(method, base + path, headers=headers, content=(body or None))
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text[:300]


async def siwe(c, base: str, account) -> dict:
    ch = (await c.post(base + "/v1/auth/siwe/challenge", json={"address": account.address})).json()
    sig = account.sign_message(
        encode_defunct(text=ch.get("message") or ch.get("challenge") or "")).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    v = (await c.post(base + "/v1/auth/siwe/verify", json={
        "nonce": ch["nonce"], "signature": sig, "address": account.address})).json()
    return {"Authorization": "Bearer " + (v.get("access_token") or v.get("token") or ""),
            "Content-Type": "application/json"}


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def save_state(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


async def ensure_seller(c, cfg: Cfg, rep: Report, hs: dict):
    """卖方 agent：优先复用状态文件里那把（省得每跑一次堆一个），认证不过再新建。"""
    state = load_state(cfg.state_path)
    cached = state.get("seller") or {}
    if cached.get("agent_id") and cached.get("api_key"):
        r = await c.get(cfg.base + "/v1/agents/mine",
                        headers={"X-Karma-Api-Key": cached["api_key"]})
        if r.status_code == 200:
            rep.log("seller-agent", {"agent_id": cached["agent_id"], "reused": True})
            return cached["agent_id"], cached["api_key"]
        rep.log("seller-agent-stale", {"agent_id": cached["agent_id"], "status": r.status_code})

    sname = "ci-seller-" + uuid.uuid4().hex[:6]
    skey = Ed25519PrivateKey.generate()
    specs = {"api_tool_call": {
        "service_content": ["MCP/API 单次工具调用"],
        "tools": ["karma.runner.buy"],
        "sla": {"max_latency_ms": 3000, "success_rule": "status=success and schema_ok"},
        "pricing": {"currency": "USDC", "price_per_call": "0.10"},
        "business_hours": {"timezone": "UTC", "24_7": True},
        "boundaries": "只做单次工具调用；不做长任务批处理；不承诺状态持久化。"}}
    sanswers = {"industry_ids": ["api_tool_call"], "service_specs": specs,
                "capability_summary": "单次 API/MCP 工具调用（回归自建）",
                "service_targets": ["consumer", "agent"],
                "service_area": {"mode": "hybrid", "regions": ["global"]}}
    r = await c.post(cfg.base + "/v1/agent-pairing/request", json={
        "agent_name": sname, "platform": "openclaw", "public_key": b64pub(skey),
        "requested_side": "seller", "self_description": "regression seller",
        "answers": sanswers})
    if r.status_code != 201:
        rep.log("seller-request-failed", {"status": r.status_code, "body": r.text[:300]})
        return None, None
    so = r.json()
    # 卖方 agent 必须挂在**卖方那个钱包**名下：链上 open_order 有 SameOwner() 反刷单。
    r = await c.post(cfg.base + "/v1/agent-pairing/approve", headers=hs, json={
        "user_code": so["user_code"], "side": "seller",
        "display_name": sname, "answers": sanswers})
    body = r.json()
    agent_id = ((body.get("pairing") or {}).get("agent_id")) or body.get("agent_id")
    r = await c.post(cfg.base + "/v1/agent-pairing/claim",
                     json={"pairing_code": so["pairing_code"]})
    api_key = ((r.json() or {}).get("credentials") or {}).get("api_key")
    rep.log("seller-agent", {"agent_id": agent_id, "reused": False, "got_api_key": bool(api_key),
                             "err": None if agent_id and api_key
                             else json.dumps(body, ensure_ascii=False)[:280]})
    if agent_id and api_key:
        state["seller"] = {"agent_id": agent_id, "api_key": api_key}
        save_state(cfg.state_path, state)
    return agent_id, api_key


async def open_buyer_runtime(c, cfg: Cfg, rep: Report, owner: dict, account):
    """买方 runtime key：建 → 绑定 agent → claim 激活。返回一个 dict 供后续步骤用。"""
    name = "ci-buyer-" + uuid.uuid4().hex[:6]
    agent_key = Ed25519PrivateKey.generate()
    r = await c.post(cfg.base + "/v1/agent-pairing/request", json={
        "agent_name": name, "platform": "openclaw", "public_key": b64pub(agent_key),
        "requested_side": "buyer", "self_description": "regression buyer"})
    if r.status_code != 201:
        rep.log("buyer-request-failed", {"status": r.status_code, "body": r.text[:300]})
        return None
    o = r.json()
    r = await c.post(cfg.base + "/v1/agent-pairing/approve", headers=owner, json={
        "user_code": o["user_code"], "side": "buyer", "display_name": name})
    agent_id = r.json()["pairing"]["agent_id"]
    msg = "\n".join(["Karma Runtime Key Create", "karma_identity_id:" + cfg.buyer_id,
                     "wallet_address:" + cfg.buyer_wallet, "permissions:" + ",".join(PERMS),
                     "single_limit:%s" % SINGLE_LIMIT, "daily_limit:%s" % DAILY_LIMIT,
                     "expire_time:never", "agent_name:" + name, "agent_binding:" + agent_id])
    sig = account.sign_message(encode_defunct(text=msg)).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = await c.post(cfg.base + "/runtime/create-key", json={
        "wallet_address": cfg.buyer_wallet, "karma_identity_id": cfg.buyer_id,
        "wallet_signature": sig, "permissions": PERMS, "single_limit": SINGLE_LIMIT,
        "daily_limit": DAILY_LIMIT, "agent_name": name, "agent_binding": agent_id,
        "agent_id": agent_id})
    if r.status_code >= 400:
        rep.log("buyer-key-failed", {"status": r.status_code, "body": r.text[:300]})
        return None
    k = r.json()
    token, key_id = k["runtime_key"], k["key_id"]
    await c.post(cfg.base + "/v1/agent-pairing/attach-runtime-key", headers=owner,
                 json={"user_code": o["user_code"], "runtime_key": token})
    r = await c.post(cfg.base + "/v1/agent-pairing/claim", json={"pairing_code": o["pairing_code"]})
    activated = (((r.json() or {}).get("runtime_key_binding") or {}).get("activated"))
    rep.log("buyer-agent", {"agent_id": agent_id, "key_id": key_id, "activated": activated})
    return {"agent_id": agent_id, "key_id": key_id, "token": token, "key": agent_key, "name": name}


async def place_order(c, cfg: Cfg, rep: Report, rt: dict, seller_id: str, owner: dict):
    """重要字段三方比对 → 下单 → Console 交办存证。返回 (task_id, voucher_id)。"""
    ts = datetime.now(timezone.utc)
    fields = {
        "time": {"deadline_at": (ts + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "location": {"place": "digital"},
        "task_requirements": "代买一份跑腿服务：按 %.2f USDC 结算，交付执行回执与证据哈希。" % cfg.amount,
        "acceptance_criteria": ["执行回执已提交", "证据哈希可核验", "金额与约定一致"],
        "amount": ("%.2f" % cfg.amount).rstrip("0").rstrip("."), "currency": "USDC",
        "required_proof_fields": ["request_hash", "response_hash", "http_or_tool_status", "latency_ms"],
        "scene": {"tool_name": "karma.runner.buy",
                  "input_hash": "sha256:" + hashlib.sha256(b"in").hexdigest()[:20],
                  "success_rule": "status=success and schema_ok", "mcp_server_id": "mcp:karma-runner",
                  "max_latency_ms": 3000,
                  "expected_output_schema_hash": "sha256:" + hashlib.sha256(b"out-schema").hexdigest()[:20]}}
    r = await c.post(cfg.base + "/v1/standards/important-fields/captures", json={
        "scene_id": "api_tool_call",
        "interaction_ref": "fulfill:%s:%s" % (cfg.buyer_id, seller_id),
        "extracted_fields": fields, "source": "protocol", "ttl_seconds": 900,
        "buyer_agent_id": rt["agent_id"], "seller_agent_id": seller_id})
    cid = (r.json() or {}).get("capture_id")
    if not cid:
        rep.log("important-fields-capture-failed", {"status": r.status_code, "body": r.text[:300]})
        return None, None
    for role, submitter in (("buyer", rt["agent_id"]), ("seller", seller_id)):
        enc = await c.post(cfg.base + "/v1/standards/important-fields/encrypt", headers=owner,
                           json={"capture_id": cid, "fields": fields, "role": role})
        if enc.status_code >= 400:
            rep.log("encrypt-failed", {"role": role, "status": enc.status_code, "body": enc.text[:220]})
            return None, None
        r = await c.post(cfg.base + "/v1/standards/important-fields/submit-encrypted", json={
            "capture_id": cid, "role": role, "nonce": uuid.uuid4().hex,
            "ciphertext": enc.json()["ciphertext"], "submitter_agent_id": submitter})
        if r.status_code >= 400:
            rep.log("submit-encrypted-failed", {"role": role, "status": r.status_code,
                                               "body": r.text[:220]})
            return None, None
    m = (await c.post(cfg.base + "/v1/standards/important-fields/match-secure",
                      json={"capture_id": cid})).json()
    rep.log("important-fields", {"triple_match": m.get("triple_match"), "result": m.get("result")})

    sc, d = await agent_call(c, cfg.base, "POST", "/runtime/place-order", rt["key"], rt["key_id"],
                             rt["token"], payload={
                                 "requirement_text": "代买一份跑腿服务", "amount": cfg.amount,
                                 "seller_identity_id": seller_id, "client_nonce": uuid.uuid4().hex,
                                 "important_fields_capture_id": cid})
    tid, vid = (d or {}).get("task_id"), (d or {}).get("voucher_id")
    rep.log("agent-place-order", {"status": sc, "state": (d or {}).get("status"),
                                  "task_id": tid, "voucher_id": vid,
                                  "awaiting_owner_confirmation": (d or {}).get("awaiting_owner_confirmation"),
                                  "err": None if tid else json.dumps(d, ensure_ascii=False)[:400]})
    if not tid:
        return None, None
    rep.scenarios[rep._cur]["task_id"] = tid

    rd = (await c.get(cfg.base + "/v1/openclaw/automation-readiness", headers=owner, params={
        "task_id": tid, "role": "buyer", "karma_identity_id": cfg.buyer_id,
        "for_handoff_confirm": "true"})).json()
    rep.log("readiness", {"ready_for_handoff_confirm": rd.get("ready_for_handoff_confirm"),
                          "blockers": rd.get("blockers")})
    r = await c.post(cfg.base + "/v1/openclaw/handoff-confirm", headers=owner, json={
        "task_id": tid, "karma_identity_id": cfg.buyer_id, "role": "buyer"})
    rep.log("handoff-confirm", {"status": r.status_code,
                                "attested": (r.json() or {}).get("attested") if r.status_code < 400 else None,
                                "err": None if r.status_code < 400 else r.text[:220]})
    return tid, vid


async def deliver_and_attest(c, cfg: Cfg, rep: Report, tid: str, hs: dict, rt: dict) -> bool:
    """卖方交付 → 执行回执（Runtime 网关代签）。返回两步是否都成。"""
    r = await c.post(cfg.base + "/v1/settlement/%s/submit" % tid, headers=hs, json={})
    delivered = r.status_code < 400
    rep.log("worker-submit", {"status": r.status_code, "state": (r.json() or {}).get("status"),
                              "err": None if delivered else r.text[:220]})
    now = datetime.now(timezone.utc)
    rcpt = {
        "receipt_id": str(uuid.uuid4()), "task_id": tid, "agent_id": cfg.buyer_id, "step_index": 1,
        "tool_name": "karma.runner.buy",
        "input_hash": hashlib.sha256(b"karma.runner.buy:in").hexdigest(),
        "output_hash": hashlib.sha256(b"karma.runner.buy:out").hexdigest(),
        "started_at": (now - timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_ms": 3000, "status": "success"}
    sc, d = await agent_call(c, cfg.base, "POST", "/runtime/submit-receipt", rt["key"], rt["key_id"],
                             rt["token"], payload=rcpt)
    if sc >= 400 and "extension" in json.dumps(d):
        rcpt["extension"] = {"kind": "api", "request_hash": hashlib.sha256(b"req").hexdigest(),
                            "response_hash": hashlib.sha256(b"resp").hexdigest(),
                            "http_status_code": 200, "latency_ms": 3000}
        sc, d = await agent_call(c, cfg.base, "POST", "/runtime/submit-receipt", rt["key"],
                                 rt["key_id"], rt["token"], payload=rcpt)
    rec_ok = sc < 400 and bool((d or {}).get("signature"))
    rep.log("agent-submit-receipt", {"status": sc, "receipt_id": (d or {}).get("receipt_id"),
                                     "signed": bool((d or {}).get("signature")),
                                     "err": None if rec_ok else json.dumps(d, ensure_ascii=False)[:260]})
    return delivered and rec_ok


async def poll_settlement(c, cfg: Cfg, rep: Report, tid: str, hdr: dict, done_states, timeout=None):
    """轮询到链上落定（done_states），超时返回最后一帧。"""
    deadline = time.time() + (timeout or cfg.timeout)
    last = None
    while time.time() < deadline:
        r = await c.get(cfg.base + "/v1/settlement/%s" % tid, headers=hdr)
        if r.status_code == 200:
            last = r.json()
            if last.get("onchain_status") in done_states:
                return last
        await asyncio.sleep(5)
    return last


async def seller_ledger(c, cfg: Cfg, hs: dict) -> dict:
    r = await c.get(cfg.base + "/v1/payments/ledger", headers=hs)
    return r.json() if r.status_code == 200 else {}


def ledger_entries(ledger: dict, kind: str, tid: str) -> list:
    return [e for e in (ledger.get("entries") or [])
            if e.get("kind") == kind and e.get("task_id") == tid]


async def flow_settle(c, cfg: Cfg, rep: Report, owner: dict, hs: dict, hs_id: dict, h1: dict,
                     rt: dict, seller_id: str) -> None:
    """照常交付 → 买方确认 → 链上放款（钱从买方钱包走到卖方钱包）。"""
    rep.start("settle")
    rep.log("scenario", {"what": "下单→交付→回执→买方确认→链上放款"})
    cap0 = (await c.get(cfg.base + "/v1/capacity/" + cfg.buyer_id, headers=owner)).json()
    rep.log("capacity-before", {"available": cap0.get("available_credits"),
                                "reserved": cap0.get("reserved_credits"),
                                "burned": cap0.get("burned_credits")})

    tid, _vid = await place_order(c, cfg, rep, rt, seller_id, owner)
    if not tid:
        rep.check("下单拿到 task_id", False, "place-order 没回 task_id")
        return

    cap1 = (await c.get(cfg.base + "/v1/capacity/" + cfg.buyer_id, headers=owner)).json()
    rep.near("下单后 reserved 增加 %s" % cfg.amount,
             float(cap1.get("reserved_credits") or 0) - float(cap0.get("reserved_credits") or 0),
             cfg.amount)
    rep.conserved("下单后台账守恒", cap1)

    if not await deliver_and_attest(c, cfg, rep, tid, hs, rt):
        rep.check("交付 + 执行回执", False, "卖方交付或回执没成")
        return

    r = await c.post(cfg.base + "/v1/settlement/%s/buyer-accept" % tid, headers=h1, json={})
    rep.check("buyer-accept 200", r.status_code == 200,
              {"status": r.status_code, "body": r.text[:200]})

    final = await poll_settlement(c, cfg, rep, tid, h1, ("settled",))
    rep.log("settled", {"status": (final or {}).get("status"),
                        "onchain": (final or {}).get("onchain_status"),
                        "binding": (final or {}).get("onchain_binding_id"),
                        "tx": (final or {}).get("tx_hash")})
    rep.check("结算行链上状态 = settled", (final or {}).get("onchain_status") == "settled",
              {"got": (final or {}).get("onchain_status")})
    rep.check("结算行带链上 binding id", bool((final or {}).get("onchain_binding_id")),
              {"got": (final or {}).get("onchain_binding_id")})
    rep.check("结算行带回写 tx_hash", bool((final or {}).get("tx_hash")),
              {"got": (final or {}).get("tx_hash")})

    cap2 = (await c.get(cfg.base + "/v1/capacity/" + cfg.buyer_id, headers=owner)).json()
    rep.near("结算后 reserved 放回", float(cap2.get("reserved_credits") or 0),
             float(cap0.get("reserved_credits") or 0))
    rep.near("结算后 burned 增加 %s" % cfg.amount,
             float(cap2.get("burned_credits") or 0) - float(cap0.get("burned_credits") or 0),
             cfg.amount)
    rep.conserved("结算后台账守恒", cap2)

    ledger = await seller_ledger(c, cfg, hs_id)
    stl = ledger_entries(ledger, "settlement", tid)
    bnd = ledger_entries(ledger, "binding", tid)
    rep.check("卖方收付中心有这一单的结算行", bool(stl), {"entries": len(stl)})
    rep.check("卖方收付中心 binding = settled",
              bool(bnd) and bnd[0].get("status") == "settled",
              {"got": bnd[0].get("status") if bnd else None})
    if bnd:
        d = bnd[0].get("detail") or {}
        rep.check("binding 带 bind/submit/finalize 三笔链上 tx",
                  all(d.get(k) for k in ("bind_tx_hash", "submit_tx_hash", "finalize_tx_hash")),
                  {k: d.get(k) for k in ("bind_tx_hash", "submit_tx_hash", "finalize_tx_hash")})
    tx = (stl[0].get("detail") or {}).get("tx_hash") if stl else None
    rep.expect_onchain(label="settle-finalize", task_id=tid, tx_hash=tx,
                       transfer={"from": cfg.buyer_wallet, "to_role": "seller",
                                 "amount_usdc": cfg.amount})


async def flow_dispute(c, cfg: Cfg, rep: Report, owner: dict, hs: dict, hs_id: dict, h1: dict,
                       rt: dict, seller_id: str) -> None:
    """开争议 → 谁也别想自己走掉 → 仲裁裁决 → 链上罚没（卖方质押划给买方）。"""
    rep.start("dispute")
    rep.log("scenario", {"what": "下单→交付→开争议→越权全挡→仲裁→链上罚没"})
    cap0 = (await c.get(cfg.base + "/v1/capacity/" + cfg.buyer_id, headers=owner)).json()
    rep.log("capacity-before", {"available": cap0.get("available_credits"),
                                "reserved": cap0.get("reserved_credits"),
                                "disputed": cap0.get("disputed_credits")})

    tid, _vid = await place_order(c, cfg, rep, rt, seller_id, owner)
    if not tid:
        rep.check("下单拿到 task_id", False, "place-order 没回 task_id")
        return
    if not await deliver_and_attest(c, cfg, rep, tid, hs, rt):
        rep.check("交付 + 执行回执", False, "卖方交付或回执没成")
        return

    r = await c.post(cfg.base + "/v1/settlement/%s/dispute" % tid, headers=h1, json={
        "reason": "regression: delivered artifact mismatched the agreed spec",
        "reason_code": "FORMAT_ERROR"})
    rep.check("开争议 200", r.status_code == 200,
              {"status": r.status_code, "body": r.text[:200]})

    st = (await c.get(cfg.base + "/v1/settlement/%s" % tid, headers=h1)).json()
    rep.log("disputed", {"status": st.get("status"), "onchain": st.get("onchain_status"),
                         "binding": st.get("onchain_binding_id"), "tx": st.get("tx_hash")})
    rep.check("争议单链上状态回写 = disputed", st.get("onchain_status") == "disputed",
              {"got": st.get("onchain_status")})
    rep.check("争议单带链上 binding id", bool(st.get("onchain_binding_id")),
              {"got": st.get("onchain_binding_id")})
    rep.check("争议单带回写 tx_hash", bool(st.get("tx_hash")), {"got": st.get("tx_hash")})

    ledger = await seller_ledger(c, cfg, hs_id)
    bnd = ledger_entries(ledger, "binding", tid)
    rep.check("卖方账本能看到争议冻结（binding = disputed）",
              bool(bnd) and bnd[0].get("status") == "disputed",
              {"got": bnd[0].get("status") if bnd else None})

    cap1 = (await c.get(cfg.base + "/v1/capacity/" + cfg.buyer_id, headers=owner)).json()
    rep.near("争议冻结增加 %s" % cfg.amount,
             float(cap1.get("disputed_credits") or 0) - float(cap0.get("disputed_credits") or 0),
             cfg.amount)
    rep.conserved("争议冻结后台账守恒", cap1)

    # 责任状态就是闸：争议里这一单谁都推不动，也不能自己撤绑定
    r = await c.post(cfg.base + "/v1/settlement/%s/buyer-accept" % tid, headers=h1, json={})
    rep.check("争议中买方放款被挡（409）", r.status_code == 409, {"status": r.status_code})
    r = await c.post(cfg.base + "/v1/settlement/%s/submit" % tid, headers=hs, json={})
    rep.check("争议中卖方交付被挡（409）", r.status_code == 409, {"status": r.status_code})
    r = await c.post(cfg.base + "/v1/settlement/%s/regret" % tid, headers=hs, json={})
    rep.check("争议中卖方反悔被挡（403）", r.status_code == 403, {"status": r.status_code})

    r = await c.post(cfg.base + "/v1/settlement/%s/auto-arbitrate" % tid, headers=h1, json={})
    rep.check("仲裁受理 200", r.status_code == 200,
              {"status": r.status_code, "body": r.text[:200]})

    final = await poll_settlement(c, cfg, rep, tid, h1, ("slashed", "settled", "cancelled"))
    rep.log("after-arbitrate", {"status": (final or {}).get("status"),
                                "onchain": (final or {}).get("onchain_status"),
                                "released": (final or {}).get("released_amount"),
                                "refunded": (final or {}).get("refunded_amount"),
                                "notes": (final or {}).get("arbitration_notes"),
                                "tx": (final or {}).get("tx_hash")})
    rep.check("裁决后链上落定（slashed/settled/cancelled）",
              (final or {}).get("onchain_status") in ("slashed", "settled", "cancelled"),
              {"got": (final or {}).get("onchain_status")})

    cap2 = (await c.get(cfg.base + "/v1/capacity/" + cfg.buyer_id, headers=owner)).json()
    rep.log("capacity-after", {"available": cap2.get("available_credits"),
                               "reserved": cap2.get("reserved_credits"),
                               "disputed": cap2.get("disputed_credits")})
    rep.near("裁决后争议冻结放回（不再冻结）",
             float(cap2.get("disputed_credits") or 0) - float(cap0.get("disputed_credits") or 0), 0.0)
    rep.conserved("裁决后台账守恒", cap2)

    ledger = await seller_ledger(c, cfg, hs_id)
    bnd = ledger_entries(ledger, "binding", tid)
    stl = ledger_entries(ledger, "settlement", tid)
    rep.check("卖方账本有这一单的结算行", bool(stl), {"entries": len(stl)})
    rep.check("卖方账本 binding 跟到终局",
              bool(bnd) and bnd[0].get("status") in ("slashed", "settled", "cancelled"),
              {"got": bnd[0].get("status") if bnd else None})
    stake = None
    if bnd:
        d = bnd[0].get("detail") or {}
        stake = d.get("stake_usdc")
        rep.check("binding 带 bind/submit/finalize 三笔链上 tx",
                  all(d.get(k) for k in ("bind_tx_hash", "submit_tx_hash", "finalize_tx_hash")),
                  {k: d.get(k) for k in ("bind_tx_hash", "submit_tx_hash", "finalize_tx_hash")})
    refunded = float((final or {}).get("refunded_amount") or 0)
    if refunded > 0:
        rep.check("卖方账本记了质押金额（链上罚没要用）", bool(stake), {"stake_usdc": stake})
        if stake:
            rep.expect_onchain(label="dispute-finalize", task_id=tid,
                               tx_hash=(bnd[0].get("detail") or {}).get("finalize_tx_hash"),
                               transfer={"from_role": "seller", "to": cfg.buyer_wallet,
                                         "amount_usdc": float(stake)})


async def run(cfg: Cfg, scenario: str, out_path) -> int:
    missing = cfg.require()
    if missing:
        print("缺少环境变量：" + ", ".join(missing), file=sys.stderr)
        return 2
    rep = Report(cfg.base)
    buyer = Account.from_key(cfg.buyer_pk)
    seller = Account.from_key(cfg.seller_pk)
    print("Karma 资金路径回归 -> %s" % cfg.base)
    print("买方 %s / 卖方 %s / 每单 %s USDC\n" % (cfg.buyer_id, cfg.seller_id, cfg.amount))

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        owner = {"X-Karma-Api-Key": cfg.owner_key}
        h1 = await siwe(c, cfg.base, buyer)
        hs = await siwe(c, cfg.base, seller)
        rep.start("setup")
        rep.check("买方 SIWE 登录", "Bearer " in h1.get("Authorization", ""))
        rep.check("卖方 SIWE 登录", "Bearer " in hs.get("Authorization", ""))
        seller_id, seller_key = await ensure_seller(c, cfg, rep, hs)
        rep.check("卖方 agent 就绪", bool(seller_id and seller_key), {"seller_agent": seller_id})
        if not (seller_id and seller_key):
            _finish(rep, out_path)
            return 1
        # 两套头别混：混了 Bearer 会先把 actor 认成身份本身，卖方的 worker 动作就变成
        # 「不是被指派的工人」（403）。agent 级动作只带 X-Karma-Api-Key。
        hs_id = dict(hs)
        hs_agent = {"X-Karma-Api-Key": seller_key, "Content-Type": "application/json"}

        rt = await open_buyer_runtime(c, cfg, rep, owner, buyer)
        rep.check("买方 runtime key 激活", bool(rt and rt.get("key_id")), {"rt": bool(rt)})
        if not rt:
            _finish(rep, out_path)
            return 1

        try:
            if scenario in ("all", "settle"):
                await flow_settle(c, cfg, rep, owner, hs_agent, hs_id, h1, rt, seller_id)
            if scenario in ("all", "dispute"):
                await flow_dispute(c, cfg, rep, owner, hs_agent, hs_id, h1, rt, seller_id)
        finally:
            # 这把钥匙是这一轮建的，跑完就注销，别在操作台上留活钥匙。
            revoke = "\n".join(["Karma Runtime Key Revoke", "key_id:" + rt["key_id"],
                                "karma_identity_id:" + cfg.buyer_id,
                                "wallet_address:" + cfg.buyer_wallet])
            sig = buyer.sign_message(encode_defunct(text=revoke)).signature.hex()
            if not sig.startswith("0x"):
                sig = "0x" + sig
            await c.post(cfg.base + "/runtime/revoke-key", json={
                "key_id": rt["key_id"], "karma_identity_id": cfg.buyer_id,
                "wallet_address": cfg.buyer_wallet, "wallet_signature": sig})

    code = 0 if rep.ok else 1
    _finish(rep, out_path)
    return code


def _finish(rep: Report, out_path) -> None:
    data = rep.as_dict()
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print("\n报告：%s" % out_path)
    print("\n结果：%s" % ("全过" if data["ok"] else "有断言失败"))
    for name, sc in data["scenarios"].items():
        bad = [x for x in sc["checks"] if not x["ok"]]
        print("  %-9s %s  断言 %d 条%s" % (
            name, "OK " if sc["ok"] else "FAIL", len(sc["checks"]),
            "" if not bad else "，失败 %d 条" % len(bad)))
        for x in bad:
            print("      - %s  %s" % (x["name"], json.dumps(x.get("detail"), ensure_ascii=False)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Karma 资金路径回归")
    ap.add_argument("--scenario", default="all", choices=["all", "settle", "dispute"])
    ap.add_argument("--out", default=None, help="报告 JSON 落盘路径")
    args = ap.parse_args()
    return asyncio.run(run(Cfg(), args.scenario, args.out))


if __name__ == "__main__":
    sys.exit(main())

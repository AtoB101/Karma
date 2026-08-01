# Evidence bundle schema (public)

`evidence.schema.json` is a **public, structural** JSON Schema. It intentionally **does not** encode private scoring,
fraud rules, or dispute weighting — those belong in the private risk engine repository.

## Important Fields Standard (market scenes)

`important-fields-standard.v1.json` — **双方 agent 可读**的重要字段标准版：

- `market_vertical`（11 垂类）
- `daily_commerce`（叫车 / 酒店 / 外卖 / 机票）
- `b2b_digital`（企业采购 / API·数据计费 / 单次工具调用）

- Docs: `docs/IMPORTANT_FIELDS_STANDARD_V1.md` · `docs/IMPORTANT_FIELDS_P5_V1.md`
- HTTP: `GET /v1/standards/important-fields`（`?group=daily_commerce`）
- Secure path (P5): protocol **capture** → role-bound AES-GCM `karma2.` submit → **triple match**
  (`buyer == seller == protocol`, sealed) via `POST …/match-secure`

## Agent onboarding templates

`agent-onboarding-template.v1.json` — **用户 / 商家 / 企业**接入模板（行业细分与 scene 对齐）。

- Docs: `docs/AGENT_ONBOARDING_TEMPLATE_V1.md`
- HTTP: `GET /v1/standards/onboarding`
- Auto-connect: `POST /v1/agents/connect-from-template`

## Human confirmation policy

`human-confirmation-policy.v1.json` — 按现实场景拆分 **AUTO / OWNER_CONFIRM / POLICY_AUTO**。

- Docs: `docs/HUMAN_CONFIRMATION_POLICY_V1.md`
- HTTP: `GET /v1/standards/confirmation-policy`
- Sessions: `POST /v1/confirmations/sessions` → owner Yes/No → fulfill continues

## Accept & fulfillment (P6)

`accept-fulfillment.v1.json` — 卖方接单 TTL、未确认档案、确认后违约责任金。

- Docs: `docs/ACCEPT_FULFILLMENT_P6_V1.md`
- HTTP: `GET /v1/standards/accept-fulfillment`
- Sweep: `POST /v1/confirmations/expire-pending-seller-accepts`

## Delivery verification (P7)

`delivery-verification.v1.json` — 交付验真：线下三方物流 + 防伪照片、票务回执 stub、数字轻量。

- Docs: `docs/DELIVERY_VERIFICATION_P7_V1.md`
- HTTP: `GET /v1/standards/delivery-verification`
- Sessions: `POST /v1/delivery-verification/sessions` → ship / intake / deliver / buyer-confirm

## Agent boundary standard

`agent-boundary.v1.json` — 每个已连接 agent 的 **能力 / 责任 / 确认** 三边界。

- Docs: `docs/AGENT_BOUNDARY_STANDARD_V1.md`
- HTTP: `GET /v1/standards/agent-boundary`
- Per agent: `GET /v1/agents/{id}/boundary`（discovery 卡附带 digest）

Align runtime tooling with:

- `trusted_agent_runtime/` (hashing + structural verification)
- On-chain `proofHash` / bill semantics in `karma-core/contracts/core/NonCustodialAgentPayment.sol`
- `Types.ServiceCategory` in `karma-core/contracts/libraries/Types.sol`

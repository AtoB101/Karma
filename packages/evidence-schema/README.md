# Evidence bundle schema (public)

`evidence.schema.json` is a **public, structural** JSON Schema. It intentionally **does not** encode private scoring,
fraud rules, or dispute weighting — those belong in the private risk engine repository.

## Important Fields Standard (market scenes)

`important-fields-standard.v1.json` — **双方 agent 可读**的重要字段标准版：

- `market_vertical`（11 垂类）
- `daily_commerce`（叫车 / 酒店 / 外卖 / 机票）
- `b2b_digital`（企业采购 / API·数据计费 / 单次工具调用）

- Docs: `docs/IMPORTANT_FIELDS_STANDARD_V1.md`
- HTTP: `GET /v1/standards/important-fields`（`?group=daily_commerce`）
- Secure path: protocol **capture** → AES-GCM `karma1.` submit → **triple match**
  (`buyer == seller == protocol`) via `POST …/match-secure`

Align runtime tooling with:

- `trusted_agent_runtime/` (hashing + structural verification)
- On-chain `proofHash` / bill semantics in `karma-core/contracts/core/NonCustodialAgentPayment.sol`
- `Types.ServiceCategory` in `karma-core/contracts/libraries/Types.sol`

# 链下积分 → 链上信誉资产

无争议完成交易会在链下累计可变积分。积分达到阈值后，由 packer **打包上链**，成为不可转让的信誉锚点（`KarmaReputationAnchor`）。这是平台内的无形资产：高信誉用户/商家可以形成信誉品牌，但 **不减免 Bilateral / FeeBridge 手续费**。达标后获得的是 **平台分红权重** 与其它非手续费奖励。大家珍惜自身信誉，系统才能正循环。

## 规则

| 路径 | 条件 | 结果 |
|---|---|---|
| 无争议打包 | 积分 ≥ 200 且成功笔数 ≥ 5，且无未过窗的违约/欺诈/争议 | `pack`，路径 `undisputed` |
| 违约/欺诈降分 | `slash`：写 `last_incident_*`，链上已打包则同步 `slash` | 分红资格冻结 90 天 |
| 90 天改过 | 同类问题 90 天内不再发生，且积分重新达到阈值 | 可再次 `pack`（`rehab_90d`） |
| 分红 | 打包分 ≥ 300 且不在冻结窗 | `rewardWeight` / `dividend_weight` |

v1 把「同类问题」落成最近一次 incident 种类（`dispute` / `default` / `fraud` / `wash`）：90 天窗口从该次事件起算。窗口内任何新 incident 会刷新时钟。

## 刷量 / 假成交（v1）

链下积分只统计**通过启发式的成交**。命中后不增加 `successful_tasks`、不加分，并可能写 `wash_trade_flags`（种类 `wash`）。打包要求 flags 低于阈值，或 90 天改过期满。发现排序会对 flags 扣分。

| 信号 | 行为 |
|---|---|
| 自成交（买卖同一 agent）或同一钱包 | 不计信誉，flags+2 |
| 粉尘额（默认 < 1） | 不计信誉；同一对家再刷则 flags |
| A↔B 对倒 | 不计信誉，flags+1 |
| 同一对家 24h 内 ≥ 4 笔 | 不计信誉，flags+1 |
| 同一卖家 60 分钟内 ≥ 8 笔 | 不计信誉，flags+1 |

五人环形刷量若每轮只打一笔、且间隔拉长，v1 可能漏检；重复对倒和短时爆发会拦住。

## API

- `GET /v1/reputation/{id}/pack-eligibility`
- `GET /v1/reputation/{id}/rewards`（`fee_waiver` 恒为 `false`）
- `POST /v1/reputation/{id}/pack`（管理员；可选 `submit_on_chain`）
- `POST /v1/reputation/{id}/slash`（管理员）

链上交易由 packer 密钥广播，**不是**用户托管密钥，也 **不是** 资金移动函数。

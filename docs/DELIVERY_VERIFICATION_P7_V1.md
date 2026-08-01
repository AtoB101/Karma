# Karma Delivery Verification P7 v1

> 目录：`packages/evidence-schema/delivery-verification.v1.json`  
> 服务：`services/delivery_verification.py`  
> API：`/v1/delivery-verification/*` · `GET /v1/standards/delivery-verification`  
> 结算闸门：`services` via `api/routes/settlement.py` submit / buyer-accept

## 目标

对照 **P5 已锁定** 的 `acceptance_criteria` / `required_proof_fields` 做交付验真。  
线下实物最难：必须 **卖方发出 → 物流核验接件 → 物流送达防伪凭证 → 买方确认**；并处理买方拖延与错件责任。

## 验真模式

| 模式 | 场景 | 要点 |
|------|------|------|
| `physical_triple` | 外卖/物流/采购/制造 | 三方确认 + 拍摄时系统标签照片 + 可选 geo/封签 |
| `ticket_stub` | 酒店/机票/教育 | 邮件回执 / 确认号 / PNR（issuer API 可后期接） |
| `ride_track` | 叫车 | 行程完成 + 轨迹/里程与锁定起终点 |
| `digital_light` | API/软件/数据 | SUCCESS 回执 + 字段覆盖；高风险禁止静默默认 |

## 线下三方状态机

```text
AWAITING_SELLER_SHIP
  → seller_shipped
AWAITING_LOGISTICS_INTAKE
  → logistics_intake_ok | WRONG_ITEM（错件共担损失 + P6 违约金）
IN_TRANSIT
  → capture-challenge（系统防伪标签）→ logistics_delivered + tagged POD
AWAITING_BUYER_RECEIPT（默认 1800s）
  → buyer_confirmed → VERIFIED
  → 超时且卖方+物流链路正确 → BUYER_SILENT_DEFAULT → VERIFIED
```

### 防伪照片

1. `POST …/capture-challenge` 下发 `nonce` + `overlay_text` + `tag_hmac`  
2. 客户端拍摄时叠加标签  
3. 上传时提交 `nonce/captured_at/geo_hash/tag_hmac` + `content_hash`  
4. 服务端重算 HMAC，防翻拍挪用  

### 买方 30 分钟默认确认（仅三方物流场景）

前置：**卖方已发出 + 物流接件 OK + 物流送达 + 防伪 POD**。  
超时未确认 → 再校验链路 → **默认确认**（金融/医疗等高风险场景禁止）。

## 额外验真手段（相对你提的要求）

| 手段 | 防什么 |
|------|--------|
| 双照片（发货+送达） | 空箱/调包 |
| Geo-fence vs 锁定 dropoff | 异地假签收 |
| 封签 QR/NFC + 交接哈希链 | 途中掉包 |
| 冷链温度证明 | 变质 |
| 高价值交接身份核验 | 冒领 |
| 票务 stub → 后期 issuer API | 假确认号 |
| 数字 usage/log hash | 计量造假 |

## Agent 用法（实物）

```text
POST /v1/delivery-verification/sessions
  {task_id, scene_id, seller, buyer, logistics, capture_id}
→ seller-ship
→ logistics-intake {item_matches:true}
→ capture-challenge {party_role:logistics}
→ logistics-deliver {tagged photo fields}
→ buyer-confirm  或  等待 30min + expire-silent-buyers
→ settlement submit / buyer-accept（须 VERIFIED）
```

## 与前后盘

| 盘 | 作用 |
|----|------|
| P5 | 锁定「验什么」 |
| P6 | 接单后武装违约责任 |
| **P7** | 交付是否真发生、货是否对、凭证是否可核 |
| P8 | 结算与信誉沉淀 |

## 相关

- `docs/IMPORTANT_FIELDS_P5_V1.md`
- `docs/ACCEPT_FULFILLMENT_P6_V1.md`
- `docs/PROOF_LAYER.md`

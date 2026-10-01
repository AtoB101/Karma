# 密钥轮换台账与操作手册（Key Rotation）

这份文档干两件事：

1. **台账** —— 每条长期密钥最后一次轮换是什么时候、谁做的、下次什么时候。这正是
   `scripts/public-beta-security-gate.sh` 里 `A2b` 判 `HUMAN` 的原因：脚本判不出
   「谁、什么时候」，必须有人签字。
2. **操作手册** —— 真要轮换时照着做，并写清每把钥匙的**代价**（有些几乎不要钱，
   有些要动全站）。

> 一条原则：**宁可写「还没轮换过」，也不要写「已轮换」。**
> 台账是给未来的自己和审计看的，一条假记录比一条空白危险得多。

下面这段是**机器可读的台账**，闸门 `A2b` 直接解析它：字段缺一个、`next_due` 与
`cycle_days` 对不上、或者已经过期，`A2b` 就判 `FAIL`。**改上面的表格时，同时改这里。**

```text
<!-- karma-rotation-ledger
scope=APP_SECRET_KEY
basis_date=2026-10-01
last_rotated=never
cycle_days=90
next_due=2026-12-30
signed_by=YMZAI
-->
```

字段口径：`basis_date` = 制度基准日；`last_rotated` = 最近一次**真**轮换日
（`never` = 从未轮换 —— **不要**把基准日填进来冒充轮换日）；`next_due` 必须等于
`last_rotated` + `cycle_days` 天（`last_rotated=never` 时以 `basis_date` 为锚）。

---

## 台账

| 密钥 | 位置（都在服务器，不进仓库） | 最后一次轮换 | 周期 | 下次计划 | 签字 |
|---|---|---|---|---|---|
| `APP_SECRET_KEY` | `/opt/karma/.env`（`chmod 600`） | **未轮换**（见下） | 90 天 | **2026-12-30** | YMZAI |
| `karma_ops-admin_…` | `/opt/karma/.env` 的 `AUTH_API_KEYS` | **未轮换** | 90 天 | **2026-12-30** | YMZAI |
| `karma_ops-arbitrator_…` | 同上 | **未轮换** | 90 天 | **2026-12-30** | YMZAI |
| `karma_ops-governance_…` | 同上 | **未轮换** | 90 天 | **2026-12-30** | YMZAI |
| `VPS_SSH_KEY`（CI 部署） | GitHub secret + 服务器 `authorized_keys` | 见 `DEPLOY_PIPELINE.md` 的「轮换」 | 破窗时 | — | — |

### `APP_SECRET_KEY` 的现状（2026-10-01 核实）

- 生效值长度 **64**；
- 回溯服务器上 **12 份** `.env` / `.env.bak-*`，最早一份是 `2026-09-02 17:09`，
  **每一份里这条 key 的指纹完全相同** → 结论：这条 key **从建网起从未轮换过**；
- **决定（2026-10-01）**：以 `2026-10-01` 作为**首次建立轮换制度的基准日**，
  周期 **90 天**，**首次真轮换计划 `2026-12-30`**。

这是「**登记基准日**」，**不是**「已经轮换过」。在 `2026-12-30` 真正做完之前，
上面台账第一列就该一直写着「未轮换」—— 谁把这一列改成「已轮换」之前，
先照本文末尾的「轮换记录」补上日期、操作人和结果。

派生的闸门项是 `A2b`（`docs/SECURITY_RELEASE_GATES.md` 的 Gate A）。它要的是
「轮换日期被记录 + 有人签字」，这两样本文都给了；它**不**要求今天就换。

---

## 为什么 `APP_SECRET_KEY` 一动就是大事

它同时是四件事的密钥材料 —— 换它等于同时换四把锁：

| 用途 | 位置 |
|---|---|
| JWT 签发 / 验签（HS256） | `api/middleware/auth.py:49,54` |
| runtime key 的 `secret_hash` 材料 | `services/runtime_key_service.py:70-82` |
| Runtime 网关响应 HMAC（`X-Karma-Response-Signature`） | `services/runtime_response_sign.py:15` |
| 「这把 key 授权给哪个 agent」的绑定声明指纹 | `services/runtime_key_service.py`（`hash_binding_scope`） |

所以「真轮换」的代价（**截至 2026-10-01，双 key 平滑能力尚未实现**）：

- **在用 runtime key 全部失效**。`secret_hash` 是用这条 key 算出来的，换 key 之后
  旧 hash 一律验不过 —— 必须重铸 + 主人重新在操作台输匹配码激活。
  2026-10-01 的实测口径：`runtime_keys` 共 **247** 行，其中 **70** 把 active。
- **SDK / 对接方**要把 `KARMA_APP_SECRET` 换成新值并重启进程，否则响应签名校验全挂
  （验证逻辑在对方手里：`sdk/runtime_client.py:93-101,339-341`）。
- 已签发的 JWT 全部失效 —— 但 JWT 只活 **15 分钟**
  （`api/middleware/auth.py:41`），所以这一项的实际代价很小。

三把运维 key（`karma_ops-*`）不一样：它们只用于 `X-Karma-Api-Key` 的静态比对
（`api/middleware/auth.py::_validate_api_key`），**不参与任何派生**。换它们没有连锁
反应，代价只是「持有者要换一把新的」。所以这三把**没有理由不按时轮换**。

---

## 操作手册 A：轮换三把运维 key（便宜，可以现在就按周期做）

```bash
# 0) 先备份（会把 .env 快照一起收进 /opt/karma/backups）
/opt/karma/repo/scripts/ops/backup.sh --verify --keep 48

# 1) 生成三把新 secret（每把 >= 24 字符，且三把互不相同）
python3 - <<'PY'
import secrets
for actor in ("ops-admin", "ops-arbitrator", "ops-governance"):
    print("%s -> karma_%s_%s" % (actor, actor, secrets.token_urlsafe(24)))
PY

# 2) 改 /opt/karma/.env 里的 AUTH_API_KEYS（三条，逗号分隔）
#    改完把新值交给对应的人（走已有的一对一通道，别贴群、别进 git）

# 3) 必须 --force-recreate：否则容器用的还是创建时冻结的那份 env
docker compose --project-name deploy --env-file /opt/karma/.env \
  -f /opt/karma/repo/deploy/docker-compose.yml up -d --no-build --force-recreate app

# 4) 自证：三把钥匙各自能用，且互不隐含
bash /opt/karma/repo/scripts/public-beta-security-gate.sh \
  --env-exec 'docker exec karma-api env' --base-url https://karma-network.ai --no-heavy
#    看 A4 / A4b / A4c 三项
```

回滚：把 `.env` 换回备份那份 + 再 `--force-recreate` 一次（备份就在
`/opt/karma/backups/.env*.bak`）。

---

## 操作手册 B：轮换 `APP_SECRET_KEY`（贵，需要维护窗口）

**在双 key 平滑能力上线之前**，这就是有损操作，按窗口做：

```bash
# 0) 备份 + 记下当前 commit（出问题要能退回去）
/opt/karma/repo/scripts/ops/backup.sh --verify --keep 48
git -C /opt/karma/repo rev-parse HEAD
cp -a /opt/karma/.env /opt/karma/.env.bak-rotate-$(date +%Y%m%d%H%M%S)

# 1) 新值（64 hex），全程不回显
NEW=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
sed -i "s|^APP_SECRET_KEY=.*|APP_SECRET_KEY=${NEW}|" /opt/karma/.env
unset NEW

# 2) 重建（同理，必须 --force-recreate）
docker compose --project-name deploy --env-file /opt/karma/.env \
  -f /opt/karma/repo/deploy/docker-compose.yml up -d --no-build --force-recreate app

# 3) 自证
curl -s -o /dev/null -w 'health %{http_code}\n' http://127.0.0.1:8000/health

# 4) 重铸 runtime key 并让主人重新激活（见 docs/runtime-key-guide.md），
#    旧的那些一起吊销 —— 别留着「验不过但还 active」的行。

# 5) 通知 SDK / 对接方换 KARMA_APP_SECRET 并重启。
```

**回滚**：把 `.env` 换回 `.env.bak-rotate-*` 那份 → 再 `--force-recreate` 一次。
旧 key 一回来，之前那些 runtime key 的 `secret_hash` 又验得过了（前提是第 4 步
没有把旧行删掉）—— 所以**第 4 步之前先确认回滚窗口已经过了**。

---

## 平滑轮换（**推荐，尚未实现**）

把上面的「有损操作」变成「改一个值 + 重启」的升级方案：

- 新增 `APP_SECRET_KEY_PREVIOUS`：签发只用新的，**验签先试新、失败再试旧**；
- `runtime key` 加**惰性迁移**：哪把 key 用旧材料验过了，就顺手用新 key 重算
  `secret_hash` 落库（需要一列记 `hash_key_version`）。⚠️ 硬约束：hash 只能拿
  **明文 secret** 算，而明文不落库 —— 所以**从没被再使用过的 key 无法替它迁移**，
  过渡期结束时要先把「仍 active 且未迁移」的这批列出来（它们就是没人用的死钥匙），
  随轮换一起吊销并**点名通知**主人。
- 网关响应 HMAC 要分两阶段翻转（老 SDK 只认 `X-Karma-Response-Signature` 一个头），
  过渡期主头继续用旧 key 签，新 SDK 走附加头。
- 过渡期上限要有硬约束（建议 30 天）+ 一个急刹车：怀疑泄露时直接清掉
  `APP_SECRET_KEY_PREVIOUS`，代价只是少量用户重新登录（JWT 只活 15 分钟）。

做完这一步，`2026-12-30` 那次真轮换就只是「改一个值 + 重启 + 看迁移率」。

---

## 轮换记录

每次轮换后**追加一行**（不要把上面的行改掉）。这一节是可核查的凭据。

| 日期 | 密钥 | 操作人 | 结果 | 备注 |
|---|---|---|---|---|
| — | — | — | — | 截至 2026-10-01，尚无轮换记录；本文建立制度与基准日 |

---

## 相关

- `docs/SECURITY_RELEASE_GATES.md`（Gate A 的 `A2b`、运维 service agent 钥匙一览）
- `docs/SECURITY_INCIDENT_PLAYBOOK.md`（泄露时「强制轮换」那一步）
- `docs/DEPLOY_PIPELINE.md`（`VPS_SSH_KEY` 的轮换）
- `docs/runtime-key-guide.md`（runtime key 的签发 / 吊销 / 重铸）
- `scripts/public-beta-security-gate.sh`（判据）

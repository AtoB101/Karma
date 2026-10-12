# 安全审计 —— 操作台今日改动全量复审 + 测试（2026-10-13）

Range: 测试网（`https://karma-network.ai`，Sepolia `TESTNET_CHAIN_ID=11155111`）。主网未动。

**本轮口径（用户 2026-10-13）**：「单独开一轮 —— 把你今天修改的内容以及补的东西都全部
审计一遍、测试一遍。」所以这份报告不是新功能设计，而是**对今天落在 `main` 的 6 笔改动
做一次复盘式审计，并把今天补的东西再补成一道能回归的门禁**。

**结论先行**

- 今天落在 `main` 的 6 笔改动（#283–#288）**CI 全绿、`Deploy to VPS` 全绿**，线上实况与仓库
  源码**字节一致**（§3）。
- 复审中发现一个**「面」上的缺口**：操作台的**资源引用**（页面 `src`/`href` + CSS `url()` +
  脚本里的路径字面量）此前**没有任何门禁** —— #288 那条背景纹理 404 就是栽在这个缺口上，
  而且本地 `file://` 打开**看不出来**（基准不一样）。本轮把它固化成
  `scripts/check_console_assets.py` + 单测 + 挂进门禁，并**拿今天那条真实旧缺陷做过负例验证**（§2）。
- 今天**没有动**任何资金状态机 / 合约 / 结算路径（§4 逐条对）。资金安全面无新增风险面。
- 本地全量 pytest：**2485 passed, 2 skipped**（44:25，`RC=0`）；操作台门禁 `rc=0`；
  两道守卫（visibility / security-baseline）`rc=0`。

## 1. 今日落地清单（审计对象）

| PR | 合并 SHA | 标题 | 碰了什么 |
|---|---|---|---|
| #283 | `24c8011` | 授权向导与「接入一个 Agent」并成一张卡 —— 一条龙单入口 | `apps/console/pages/cyber/index.html`、`scripts/cyber-authorize.js`、`cyber-agents.js`、i18n 五门语言、`tests/js/test_console_agent_onestop_merge.cjs` |
| #284 | `6d7aa41` | 补齐一条龙合并卡的静态文案（五门语言） | `i18n-phrase/*.js`、`tests/js/test_console_agent_onestop_i18n.cjs` |
| #285 | `e84bafb` | 操作台入口收口到 `/console`，深链不再被入口那一跳吃掉 | `services/chat_adapters/config.py`（只改默认 URL 常量）、`.env.example`、`cyber-console.js` 落点表、vhost（线上） |
| #286 | `9a8f5e5` | Agent 接入归主身份 —— 向导只选卡起名，不再重填边界 | `cyber-authorize.js`、`karma-public-api.js`（`suggestIndustries`）、`cyber-bind-requests.js`、单测 |
| #287 | `28ec4d3` | 操作台短入口 `/console` 不再跳转，地址栏就停在 `/console` | vhost（线上，`alias` + `<base>` 注入），仓库侧只补审计文档 |
| #288 | `65dee16` | 修掉降落球背景纹理一直 404 的路径 | `styles/cyber-console.css`（1 行）、页面 `?v=` 重打 1 处 |

公开面全部是**操作台静态资源 + 文案 + 入口路由**；服务端侧只有一处**非机密默认地址常量**
（`DEFAULT_CONSOLE_BASE_URL`），以及 API 客户端新增一个只读的行业建议调用（`suggestIndustries`）。
没有任何一笔改到资金状态机、合约、结算或密钥路径。

## 2. 本轮「补的东西」——资源引用审计固化成门禁

### 2.1 为什么这是真缺口

#288 的根因：`.globe-fallback` 的背景纹理写成 `url("../../assets/earth-texture.jpg")`。
CSS 的 `url()` 相对**样式表自己**解析，样式表在 `/console/styles/`，往上**两**级 = 站点根，
于是浏览器一直去要 `/assets/earth-texture.jpg`（线上 **404**）；文件其实在 `/console/assets/`，
只该往上**一**级。那条纹理从来没加载过 —— 但它不报错、不影响功能，只安静地少一张背景。

这类「引用落不到文件」的错，**没有任何既有门禁覆盖**：

- `scripts/stamp_console_assets.py --check` 只管「有没有挂 `?v=`、版本串跟内容对不对」，
  遇到指不存在的文件反而是**跳过**（注释里写得很清楚：让页面自己的 404 曝出来）；
- `scripts/console_bundle.py` 只管「文件级清单跟发布物对不对」，不看页面上引用了谁。

### 2.2 新增：`scripts/check_console_assets.py`

把每一个引用按它**真实的线上 URL 口径**解析回仓库文件，逐个确认存在：

- 页面（短入口 `/console` 与长路径 `/console/pages/cyber/index.html`）文档基准都是
  `/console/<页面所在目录>/`（短入口由 vhost 注入 `<base href>`，等价于页面自己那一层）；
- CSS `url()` 相对**样式表自己**（`/console/styles/<name>.css` 的所在目录）；
- 脚本里的路径字面量相对**加载它的页面**（只查真的被某页 `<script src>` 加载过的脚本 ——
  没人加载的脚本里的路径指不到浏览器）；
- 不是本地资源的引用（`http(s)://`、`//`、`data:`、`#`、`mailto:`、`javascript:`、`blob:`、`tel:`）
  与指向 `/console/` 之外的**绝对**路径（如同源 API 的 `/v1/...`）一律跳过。

输出两类问题：**逃出 `/console/` 前缀**（往上多算一级）与 **404**（文件不存在）。

```bash
python scripts/check_console_assets.py             # 默认 --check：有问题退出码 1
python scripts/check_console_assets.py --selftest  # 用临时夹具自证能抓到 ../../ 这类错
```

仓库现状：**解析并检查 47 条引用，全部命中文件（0 问题）**。

### 2.3 负例验证（不是推演，是真跑）

把仓库那份 `apps/console` 复制到临时目录，只把 `styles/cyber-console.css` 第 2843 行**还原成
修前的写法**（`url("../../assets/earth-texture.jpg")`），再跑审计：

```
checked: 47
BAD styles/cyber-console.css:2843 url() ../../assets/earth-texture.jpg -> /assets/earth-texture.jpg | 逃出 /console/ 前缀
issues: 1
```

—— 定位精确到文件与行号，并且只有这一条（不误报）。这就是「这道门禁真能拦下今天那个 bug」的证据。

### 2.4 新增单测 + 挂进门禁

- `tests/unit/test_console_asset_links.py`（5 条）：仓库现状 0 问题、健康夹具 0 问题、
  「往上多算一级」被抓（分类为「逃出 /console/ 前缀」）、指向不存在文件被抓（404）、
  工具自检通过。
- `scripts/acceptance/console_last_mile_gate.sh`：在 `stamp_console_assets.py --check` 之后
  挂 `python3 scripts/check_console_assets.py`，并在 pytest 清单里加 `test_console_asset_links.py`。

本地实跑：

```
python -m pytest -q tests/unit/test_console_asset_links.py  -> 5 passed
bash scripts/acceptance/console_last_mile_gate.sh            -> OK  cyber console gate finished (rc=0)
```

## 3. 测试证据（本地 + CI + 部署 + 线上）

### 3.1 本地全量 pytest

```
python3 -m pytest tests packages/karma-openmanus/tests packages/karma-openclaw/tests \
  packages/karma-mcp-server/tests packages/karma-connect/tests -q --tb=short -p no:cacheprovider
-> 2485 passed, 2 skipped, 1 warning in 2665.64s (0:44:25)   RC=0
```

（日志 `work/logs/accept.out.txt`。规模：`tests/` = 2340（unit 1915 / integration 207）、
openmanus 4、openclaw 40、mcp-server 78、karma-connect 25。Windows 本机 API/integration 用例
每条 ~2–4 秒（IO 慢），全量 ~44 分钟是正常耗时，不是挂死。）

### 3.2 CI（同一 SHA 的权威口径，`main` 上）

今日 6 笔合并提交在 `main` 上触发的 workflow **全部 completed / success**：

| SHA | runs | Deploy to VPS | 其余 |
|---|---|---|---|
| `24c8011` (#283) | 7 | success | Forge CI / MCP packages / Python tests / Security Baseline Guard / Security CI / Visibility Guard 全 success |
| `6d7aa41` (#284) | 7 | success | 同上 |
| `e84bafb` (#285) | 7 | success | 同上 |
| `9a8f5e5` (#286) | 7 | success | 同上 |
| `28ec4d3` (#287) | 7 | success | 同上 |
| `65dee16` (#288，main tip) | 7 | success | 同上 |

`main` tip = `65dee16f76391a6b99bb63896fcdb03213af9ac5`（#288）。#288 的 PR 分支头 `84405c5`
另有 9 个 run（含 `PR Migration Impact`），也全 success。

### 3.3 线上复验（`https://karma-network.ai` 直连，2026-10-13 本轮）

```
/console                                   200  text/html（无 Location）
/console/                                  200  text/html
/consle                                    301  -> https://karma-network.ai/console
/health                                    200  application/json
/console/assets/earth-texture.jpg          200  image/jpeg  len=1392914
/assets/earth-texture.jpg                  404                <- 证明修前那条路径确实是死路
线上 CSS 那条：2843  background-image: url("../assets/earth-texture.jpg");
短入口 <base href="/console/pages/cyber/"> 出现次数：1（长路径 0）
```

**字节级一致性**（LF 归一化后，跨平台可比）：

```
/console/pages/cyber/index.html        == 仓库 apps/console/pages/cyber/index.html    identical (127847 B)
/console  去掉那 1 个 <base>            == 仓库同一份页面                             identical (127882 = 127847 + 35)
/console/styles/cyber-console.css      == 仓库 apps/console/styles/cyber-console.css  identical
/console/scripts/cyber-console.js      == 仓库同一份脚本                             identical
```

抽查的 CSS 内容摘要 `sha256(LF)[:12] = 58da3ce15004`，与页面里引用的 `?v=58da3ce15004` 一致 ——
「页面 → 资源」两级拿到的是同一版，这正是 #288 重打戳要保证的。

### 3.4 门禁与守卫

```
bash scripts/acceptance/console_last_mile_gate.sh   -> rc=0（含新挂的 check_console_assets + 新单测；
                                                         i18n 全量扫描 8145 句漏译 0；view 落点 20 checks）
bash scripts/visibility-guard.sh --staged           -> PASS
bash scripts/security-baseline-guard.sh             -> OK（金融函数注册表与合约源一致）
```

## 4. 资金安全面逐条核对（今天没动，如实对）

| 面 | 今天是否触碰 | 依据 |
|---|---|---|
| 交易状态机 / 订单 / Bill / Evidence / Receipt | 否 | 今日 diff 无 `services/`（除 `chat_adapters/config.py` 一个常量）、无 `api/routes/`、无 `contracts/` |
| 资金锁定 / 结算 / 退款 / 争议 | 否 | 同上 |
| 密钥铸造 / 运行期网关 / 激活闸门 | 否 | `services/runtime_key_service.py`、`api/routes/runtime_gateway.py` 不在今日 diff |
| NonCustodialAgentPayment | 否 | 未触碰 |
| 授权策略与额度（向导 UI 侧） | 是（**只改前端表单形态**） | #286 把「建子身份」时已设的边界从接入向导里去掉（不重复填），额度/边界的**服务端校验与状态机一字未改**；`tests/unit/test_console_authorize_wizard.py` 钉住 |
| 服务端默认操作台地址 | 是（**非机密常量**） | `DEFAULT_CONSOLE_BASE_URL` 由 `https://karma-network.ai` 改为 `.../console`，只影响引导链接指向 |

结论：今天的改动面在**前端表单形态 / 文案 / 入口路由 / 静态资源路径**，资金状态机与结算路径
**零改动**，未引入新的资金风险面。

## 5. 回滚

- **仓库侧**：6 笔改动都是普通提交，`git revert <sha>` 即可（squash 提交，单笔可逆）。
- **线上 nginx（不在仓库）**：`/www/server/panel/vhost/nginx/karma-site.conf` 留了两份备份
  —— `.bak-console-short2-20261013-040932`（本轮之前那一版，302 版）、
  `.bak-console-short-20261013-040827`（第一版尝试）。换回 + `nginx -s reload`。
- **静态站**：`/www/wwwroot/console/`，由 `karma-web-deploy` 从 `apps/console` 发布；
  它**不写** nginx 配置，所以下次部署不会冲掉 vhost 改动。
- 新挂的门禁（`check_console_assets.py`）若误报，可临时从 `console_last_mile_gate.sh` 摘掉
  那一行 + 那条单测，不影响线上（它是纯静态检查，不在发布路径上）。

## 6. 未做 / 未验证（如实记，不声称已做）

- **主网真实资金**：未动（用户口径：测试网先做到商业级，再主网测试）。
- **Playwright 真机验证**：本地与 CI 均未安装 `playwright`，门禁里那一支是 **skip**。
  本轮真机等价证据用的是**字节级服务端校验**（§3.3）：长路径响应 == 部署文件；
  短入口响应 == 部署文件 + 恰好 1 个 `<base>`。
- **vhost 未纳入仓库**：历史口径（「发过的产物」），本轮没改这一点，只在审计里记明。
- **`tests/js/*` 之外的 JS 分支覆盖**：门禁挂了 13 个 `.cjs` 行为套件，但没有全操作台单测覆盖率数字。
- 更早提过、不在本轮范围的：**G10 需发布负责人逐项签字**、**G11 KYC 侧对外公开留痕接口**。
- 旧审计 `security/audit/2026-10-13-console-entry-and-deeplink-audit.md` §7「顺带发现（未修）」里
  那条背景纹理 404，**本轮已修**（#288），该处状态已被本报告取代。
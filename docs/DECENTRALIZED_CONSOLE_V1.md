# 去中心化操作台 · L1/L2 落地说明

**状态**：L1（静态包分发）、L2（节点层）已落地并进入验收闸门；
L3-1 里属于操作台的那半（核验页折叠成 3 步 + 服务商通道明确置灰）也已落地。
L3 的身份面（走服务商签名 / 质押开通治理岗）与 L4（只读节点）只是路线图。

这份文档回答一个问题：**操作台现在离「谁都能自己跑一份」还有多远，差在哪。**

---

## 一、为什么先做 L1/L2

操作台是纯静态页面（`apps/console`，没有构建步骤），但「跟谁说话」原来写死在代码里：

- `apps/console/scripts/karma-public-api.js` 的默认地址是 `http://127.0.0.1:8000`，
  线上靠同源反代兜住；
- `apps/console/scripts/cyber-handoff.js`、`cyber-authorize.js` 里有一个
  `RUNTIME_URL = "https://karma-network.ai"`，**交付给 agent 的 env 和自检 curl 用的就是它**。

第二条是真正的问题：用户在操作台里做的任何选择，都传不到 agent 手里。
换句话说，就算我们放出第二台节点，用户也换不过去 —— 换了，agent 还在敲厂商的机器。

所以顺序是：**先把「换节点」这件事做成真的**（L2），**再谈把静态包发到内容寻址存储上**（L1）。
反过来做的话，IPFS 上那份页面还是只会连厂商一个地址，等于没变。

---

## 二、L2 · 节点层（已落地）

### 代码

| 文件 | 职责 |
|---|---|
| `apps/console/scripts/karma-nodes.js` | 节点表 / 探活 / 容灾 / 持久化（纯逻辑，无 DOM） |
| `apps/console/scripts/cyber-node-panel.js` | 顶栏胶囊 + 下拉 + 设置页卡片（只负责画和接事件） |
| `apps/console/scripts/karma-public-api.js` | 取地址改走节点层；请求失败时喊一声容灾 |
| `apps/console/scripts/cyber-console.js` | 同上（`displayBase()`） |
| `apps/console/scripts/cyber-handoff.js`、`cyber-authorize.js` | 交给 agent 的地址改走节点层 |

### 唯一的「事实来源」没有变

选中哪台节点，仍然记在 `localStorage["karma_cyber_api_base"]` 里 —— 和改动之前是同一个键。
切节点就是改这个键，外加同步 `window.KARMA_API_BASE`。这样：

- 其它脚本不用改口径；
- 老用户已有的本地设置不失效；
- 在「连接设置」里手填过自建地址的人不会被悄悄甩到别处。

最后一条是特意做的：**手填的地址如果不在节点表里，会作为一个条目显示出来**
（`legacy:<地址>`），用户看得见、能切走、能删掉。不做这一步的话，
`current()` 会退回到列表第一条，用户手填的节点会被静默替换成「当前站点（同源）」。

### 内置引导节点

| id | 地址 | 说明 |
|---|---|---|
| `same-origin` | `""`（空串 = 同源） | 默认。本机打开时解析成 `http://127.0.0.1:8000` |
| `official` | `https://karma-network.ai` | 官方入口，现在是镜像之一 |
| `local` | `http://127.0.0.1:8000` | 只在页面本身跑在本机时出现（https 页面连 http 会被浏览器拦掉，露出来只会让人困惑） |

用户还能自己加最多 8 台，地址必须是 `http(s)://`（`javascript:` / `data:` 一律拒绝）。

### 探活与容灾

- 探活打 `GET /health`（`{"status":"ok","version":"0.1.0"}`），量一次往返耗时；
  顶栏胶囊上显示绿色/红色/灰色圆点 + 毫秒数。
- **记录形状统一带 `tested` 字段**：`list()` 和单次 `probe()` 写进缓存的形状必须一致，
  否则「还没测过」和「测过且通过」在界面上分不开（这个坑踩过一次）。
- 容灾默认**关闭**，用户在设置页勾选后开启。开启时，当前节点探活失败 →
  按顺序探其它节点，第一台能用的就切过去，并把选择记住。
  有 15 秒最小间隔和重入锁，不会因为并发请求把节点来回甩。

### 交给 agent 的地址

`cyber-handoff.js` 和 `cyber-authorize.js` 里各有一个 `runtimeUrl()`：

```
KarmaNodes.effectiveBase()  →  KARMA_RUNTIME_URL=<选中的节点>
                            →  自检 curl 里的地址
```

两边都挂在各自命名空间上（`KarmaHandoff.runtimeUrl` / `KarmaAuthorize.runtimeUrl`），
配对面板和测试复用同一份实现，不各写一套。

### 线上复验抓到的两件事（已修）

第一次把「线上复验」跑起来（`tests/playwright/console_nodes_prod.cjs`，打真域名）
就抓到两个真问题，都不是靠读代码看出来的：

1. **选了一台连不通的节点，整个操作台会挂住。** 客户端的 `fetch` 原来没有截止时间，
   于是请求永远不返回：实测十个请求挂了十几秒还在 pending，界面只能一直转圈 ——
   用户分不清是节点的问题还是自己网断了。现在每次请求都带 15 秒截止
   （`AbortSignal.timeout`），超时走和「连不上」同一条路：明确失败 + 通知节点层。
2. **切语言可能一直切不过去。** 语言包是动态插 `<script>` 取的；同源连接被占住时，
   浏览器把它们排在低优先级，几百 KB 的包挂十几秒都不回来 —— 而同一个地址用
   `fetch` 取，1 秒就回来了（线上实测，不是推测）。现在改成 `fetch` 取回来挂成 blob
   执行；并且**失败不再被记死**：以前一次抖动会让这个会话永远停在上一种语言，
   现在会换一个查询串重试一次。

---

## 三、L1 · 静态包分发（已落地）

### 代码

| 文件 | 职责 |
|---|---|
| `scripts/console_bundle.py` | `build` 复制干净静态包 + 逐文件 sha256 清单；`verify` 对账；`stamp` 写回 CID |
| | `remote`：拿线上 / 镜像上真正发出去的那份跟本地源码对账（部署后的最后一道） |
| `scripts/publish_console_ipfs.sh` | 构建 → 自校验 → 有 `ipfs` 就 pin 并写 DNSLink，没有就打印照做能成的命令 |

### 清单长什么样

```json
{
  "schema": "karma.console.dist/v1",
  "generated_at": "2026-01-01T00:00:00Z",
  "src": "apps/console",
  "ipfs": { "cid": null, "dnslink": null, "gateway": null, "pinned_by": null },
  "files": [{ "path": "index.html", "sha256": "…", "bytes": 1234 }],
  "file_count": 39,
  "total_bytes": 2196425,
  "root_sha256": "…"
}
```

`root_sha256` = 各文件摘要按 `"<sha>  <path>\n"` 串起来再哈希。
**确定性的**：同一份源码，两次构建的 `root_sha256` 必然相同；只改 `generated_at` 不影响它。
所以「我手上这份跟你发布的那份是不是同一份」是个可以当场算出来的问题。

`verify` 会指出四类问题：少文件、多文件、内容被改、总摘要被改（逐个文件都对但清单被动过手脚）。

摘要按 **LF 规范化之后**算：Windows 检出是 CRLF、Linux 是 LF，同一份源码在两台机器上
必须得到同一个 `root_sha256`，否则「线上那份跟我手上这份是不是同一份」在跨平台时永远对不上。
边界也要说清楚：**CID 不是跨平台可比的**（CID 认的是真实字节），所以正式发布固定从一个平台出。

`remote` 是部署后的最后一道：把线上（或任意镜像、`file://` 目录）真正发出去的那份，
逐文件跟本地源码对账。本地 `verify` 只能证明「我这份目录跟我这份清单一致」，
证明不了「线上那一份就是我这份」—— 少推一个文件、nginx 还发着旧包，
都只有真的去取一遍才知道。

### 为什么不在 VPS 上跑 IPFS

`deploy/vps/ci-deploy.sh` 里写着：那台机器只有 1.6G 内存，装包压垮过一次。
所以发布从本机 / CI 走，官方站点从此只是**镜像之一**：

```
_<domain>  TXT  "dnslink=/ipfs/<cid>"
```

配好这条 TXT 之后，任何网关（含官方站点）都能解析到这份静态包。

---

## 四、L3 / L4：做到哪一步了

### L3-1 · 认证走服务商签名

`services/identity_provider/` 已经有 aliyun / tencent / persona / mock 四家，
以及回调验签（`signature.py`）—— 这一层不用动。

**操作台这半已经落地（2026-09-23）**，做掉的是让用户站着猜的两件事：

1. **核验从 5 段折成 3 步。** 原来的 ① 证件 ② 刷脸 ③ 识别 ④ 本地加密 ⑤ 提交
   里，「④ 本地加密」根本不是用户要做的一步，它只是提交那一刻发生的事。
   现在是 ① 证件 ② 刷脸 ③ 本地加密并提交，跟个体 / 企业两张认证页的写法一致；
   被脚本写过的两个状态位（`idv-enc-state` / `idv-send-state`）折进这一步里，没丢。
2. **两条通道不再并排摆着。** 服务商没接入（或密钥没配齐）时，那张卡加 `is-off`
   变灰 + `aria-disabled="true"`；人工复核那张卡在页头标出「当前路径」，
   服务商接上之后自动换成「备用路径」。走哪条不用猜，也不用问客服。

这两条都有测试盯着：`tests/unit/test_console_verify_route.py`（静态契约）+

顺带修了一个量出来的小毛病：通道标记是脚本写进 DOM 的，而页面翻译是**排队异步**跑的 ——
写完不等一轮，切完语言会先看见中文（线上复验里量到的）。现在写完立刻对这一个节点翻一次。

这两条都有测试盯着（另有上面那个 prod 变体）：`tests/unit/test_console_verify_route.py`（静态契约）+
`tests/playwright/console_verify_route_live.cjs`（真浏览器：数步骤、看灰没灰、
六门语言逐个切一遍 —— 英文页里不该看见一个汉字）。

**还没做的是另一件事：真正的自动通过。** 线上 `IDENTITY_PROVIDER` 仍是未设置状态，
所以「开 session → 回调 → 验签 → 自动置位」这条链在生产上还没有服务商接上；
按现在的状态，认证仍然由复核台人工核验。

> 测试网可以先配 `IDENTITY_PROVIDER=mock` 把整条链路跑通。
> `config/settings.py` 已经硬性禁止 mock 上生产。

### L3-2 · 复核 / 仲裁：质押即开通

今天要开治理岗，得进 `GOVERNANCE_VERIFIER_IDS` 白名单（`identity_role_profiles.py` 的
`GOVERNANCE_CLASSES`）。这是中心化的。替代方案是质押：押金到位即开通岗位，
误判按已有的 `stakeAmount` / `StakeSlashed` / `finalizeBreach` 罚没。
`api/routes/allowance_escrow.py` 里这套已经在了，缺的是「把它接到岗位开通上」。

### L4 · 只读节点

把读接口做成无状态的、再加一个链上事件索引器，任何人 `docker compose up` 起一台
只读节点就能进操作台的节点列表。这是 L2 的自然延伸 —— L2 把「换节点」做成真的，
L4 才有意义。

---

## 五、诚实边界：现在还有哪些是中心化的

不写清楚这一节，前面的「去中心化」就是营销词。

1. **写路径仍然要会话鉴权。** 锁仓、授权、放款这些要钱包签名，但**提交**要走
   我们这台 API 的会话令牌。会话是我们签发的 —— 换节点不能绕开这一点。
2. **回执与调用留痕存在服务端。** 「已绑定钥匙」的最近调用记录、取消绑定的站内提醒
   都在我们的库里。这是「事后能对账」的地基，暂时没有链上等价物。
3. **L3-2 落地之前，治理岗还是白名单。** 也就是说「谁是复核员」现在由我们说了算。
4. **法定 AML/KYC 只能由持牌服务商承担。** 这一条不会因为去中心化而消失，
   L3-1 做的是把「Karma 自己存证件」换成「Karma 只验签名」。

所以准确的说法是：**操作台的分发与接入已经可以去中心化，资金路径本来就在链上，
但身份核验与写路径的会话仍然是中心化的。** 这三件事分开看，不要合并成一句口号。

---

## 六、自己跑一份

```bash
# 1. 拿静态包（或直接用仓库里的）
python3 scripts/console_bundle.py build --src apps/console --out dist/console

# 2. 校验它没被动过
python3 scripts/console_bundle.py verify --dir dist/console

# 3. 起一个静态服务器
python3 -m http.server 8787 --directory dist/console

# 4. 打开 http://127.0.0.1:8787/pages/cyber/index.html
#    顶栏「节点」胶囊 → 添加你自己的节点地址 → 切过去
```

节点要能被选上，必须满足两件事：

- `GET <你的地址>/health` 返回 `{"status":"ok", ...}`；
- 允许操作台那个来源跨域取数（`CORS_ALLOW_ORIGINS`，或用同源反代
  —— 同源是推荐做法）。

---

## 七、验收

```bash
bash scripts/acceptance/console_last_mile_gate.sh
```

闸门里跟这次改动有关的部分：

- 逐字检查 `karma-nodes.js` / `cyber-node-panel.js` 存在、被页面加载、加载顺序在 API 客户端之前；
- 检查 `KarmaNodes.effectiveBase` 出现在 API 客户端、页面引导、两个交付包里；
- **反向**检查两个交付包里不再有写死的 `RUNTIME_URL = "https://karma-network.ai"`；
- `tests/unit/test_console_nodes.py`：节点层的静态契约 + 「这两个文件里的中文必须 5 份语言包全覆盖」；
- `tests/unit/test_console_distribution.py`：清单可复现、校验能抓出四类不一致；
- `tests/js/test_karma_nodes.cjs`：53 项行为断言（选节点 / 探活 / 超时 / 容灾 / 自定义节点校验 / 手填地址不被替换）；
- `tests/unit/test_console_verify_route.py`：核验页只剩三步 + 服务商通道没接入时必须是灰的（+ 状态位没被折丢）；
- `tests/playwright/console_verify_route_live.cjs`：真浏览器 27 项（数步骤 / 看灰没灰 / 六门语言逐个切、日文页按「中文原文有没有原样留下」判残留）；
- `tests/playwright/console_verify_route_prod.cjs`：同一套断言打**线上**（需要显式给 `KARMA_PROD_URL`，闸门里不跑）—— 证明发出去的那份在真浏览器里真的长这样。
- `tests/js/test_console_fetch.cjs`：请求必须有截止时间（挂住的请求会被中止 + 通知节点层）；
- `tests/playwright/console_nodes_live.cjs`：真实浏览器 46 项（装了 playwright 才跑）——
  选节点 / 探活 / 容灾 / 六门语言不留中文 / 容灾提示里的节点名也跟着语言走，
  其中一节故意让语言包第一次返回 503，验证它还会重试并能切成目标语言。

部署之后还有两条**打线上**的复验（闸门里不跑，需要手动给地址）：

```bash
# 逐字节对账：线上 39 个文件跟本地源码是不是同一份
python3 scripts/console_bundle.py remote --src apps/console --base https://karma-network.ai/console/

# 真浏览器在正式站点上把节点层从头走一遍
KARMA_PROD_URL=https://karma-network.ai/console/pages/cyber/index.html \
  node tests/playwright/console_nodes_prod.cjs
```

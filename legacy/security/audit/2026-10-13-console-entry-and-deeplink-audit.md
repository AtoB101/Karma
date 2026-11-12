# 安全审计 —— 操作台入口收口 + 深链可达性（2026-10-13）

Range: 测试网（`https://karma-network.ai`，Sepolia `TESTNET_CHAIN_ID=11155111`）。主网未动。

**口径（用户 2026-10-13 拍板，方案 1）**：操作台入口就是 `https://karma-network.ai/console`。

**结论先行**：入口收口完成，并且**实修一个线上真缺陷** —— `/console/` 那一跳把查询串
丢了，所以文档里承诺过的 `?pair=<user_code>` 深链在线上从来没走到过前端。主人点开 agent
给的链接只会看到默认的订单页，得自己在侧栏里翻「接入一个 Agent」在哪 —— 这正是用户实测
「匹配码在哪输入 / 找不到位置」的**机器侧原因**。本轮不碰资金状态机，未发现资金安全面新增风险。

## 1. 方法与证据

| 检查面 | 做法 | 结果 |
|---|---|---|
| 线上入口行为 | 在 VPS 本机 `curl`（绕过 CDN）/ 从外部 `urllib`（不跟跳转，只读 `Location`） | §3 表 |
| 操作台深链落点 | 把 `cyber-console.js` 真跑一遍（假 DOM），逐个地址断言哪一页 `active` | `node tests/js/test_console_view_landing.cjs` → **18 checks 通过** |
| 适配器 ↔ 操作台名字契约 | 适配器发的 `?view=` 名字必须都在操作台的落点表里 | `pytest tests/unit/test_chat_adapters.py` → **35 passed** |
| 操作台整条门禁 | `bash scripts/acceptance/console_last_mile_gate.sh` | **rc=0**（含新挂进去的那条深链用例） |
| 回滚 | 两个 vhost 都留了 `.bak-console-<ts>` | 见 §5 |

## 2. 发现与修复

| # | 现象（修前） | 风险 | 处理 |
|---|---|---|---|
| F1 | `/console/?pair=ABCD-1234` 302 到 `/console/pages/cyber/index.html`，**查询串被吃掉** | 高 —— 主人侧配对深链、`?view=` 引导链接整条失效；文档承诺的流程实际不可达 | vhost 那一跳补 `$is_args$args` |
| F2 | `/console` → 302 `/console/` → 302 `/console/pages/cyber/index.html`（**两跳**） | 低 —— 多一跳、多一次日志 | 两条精确匹配都直接一跳落到操作台 |
| F3 | `/consle`、`/consle/` 都是 **404**（少打一个 o） | 低 —— 手滑就进不去，用户以为站点挂了 | 加 301 收口到 `/console` |
| F4 | 代码默认 `KARMA_CONSOLE_BASE_URL = https://karma-network.ai` | 中 —— 官网首页是营销页，主人按引导点进去找不到批准入口 | 默认值改成 `https://karma-network.ai/console` |
| F5 | 操作台**不解析** `?view=pairing` / `?view=agents` | 中 —— 链接能把人送进操作台，但仍停在默认页，得自己翻侧栏 | `cyber-console.js` 加落点表（认不出就落默认页） |

`app.karma-network.ai`（旧控制台域名）的同一条跳转也一起补了 `$is_args$args`，口径与主域名一致。

**为什么 F1 是这轮最值钱的一条**：`services/agent_pairing.py` 发的
`verification_uri` 就是 `{KARMA_RUNTIME_URL}/console/?pair=<user_code>`，
`services/chat_adapters/config.py` 发的接入引导是 `{base}/?view=pairing`。
两条链接都栽在同一跳上 —— 前端代码（`cyber-pairing.js` 的 `prefillFromUrl`）一直是好的，
坏的是中间那一跳。

## 3. 线上实测（修后，VPS 本机）

```
/console                                   302 -> https://karma-network.ai/console/pages/cyber/index.html
/console/                                  302 -> https://karma-network.ai/console/pages/cyber/index.html
/console/?view=pairing                     302 -> https://karma-network.ai/console/pages/cyber/index.html?view=pairing
/console/?pair=ABCD-1234                   302 -> https://karma-network.ai/console/pages/cyber/index.html?pair=ABCD-1234
/consle                                    301 -> https://karma-network.ai/console
/consle/                                   301 -> https://karma-network.ai/console
/console/pages/cyber/index.html            200
```

修前对照：

```
/console/?pair=ABCD-1234  302 -> https://karma-network.ai/console/pages/cyber/index.html   <- 查询串没了
/console                  302 -> https://karma-network.ai/console/                          <- 还有第二跳
/console/                 302 -> https://karma-network.ai/console/pages/cyber/index.html
/consle                   404
/consle/                  404
```

## 4. 深链落点（操作台侧，真跑过）

| 地址 | 落点 | 证据 |
|---|---|---|
| 没有 `view` | 订单页（默认页不动） | 18 checks 里的 1 条 |
| `?view=pairing` | `#agents` 页 + 「接入一个 Agent」子项高亮、父项 `parent-active` | 同上 |
| `?view=agents` | `#agents` 页 + 「我的助理 Agent」子项高亮 | 同上 |
| `?view=<认不出的值>`（含 `Pairing` 大写、`../../etc/passwd`） | 订单页 | 同上 |
| `?pair=CODE` | 订单页 —— 这条链接由 `cyber-pairing.js` 自己收（还要把码预填进输入框） | 同上 |
| 宿主没有 `location` | 不炸，落订单页 | 同上 |

**侧栏可见性不在这一层**：主身份档按 `applyNavScope` 本来就不挂 `agents` 组，所以深链落点
**不依赖侧栏可见**（页 + 子项高亮照样成立）；切到助理身份档（`individual` / `merchant` /
`enterprise`）时那一组本来就是可见且展开的。这一条也在用例里钉住了，避免以后有人
「为了让侧栏亮起来」去改收窄规则。

## 5. 回滚与运维

- 改动只在服务器上这两份 vhost（仓库里没有 nginx 模板，vhost 是发过的产物）：
  `/www/server/panel/vhost/nginx/karma-site.conf`、`karma-app.conf`；
  各自留了 `.bak-console-<ts>`；改完 `nginx -t` + reload。
- 回滚 = 把 `.bak-console-<ts>` 换回去再 reload。
- 静态站在 `/www/wwwroot/console/`，由 `karma-web-deploy` 从 `apps/console` 发布
  （`deploy/vps/ci-deploy.sh` → `deploy/karma deploy` → `publish_web`）；它**不写** nginx 配置，
  所以 vhost 的改动不会被下次部署冲掉。

## 6. 边界与未做（如实记）

- `?view=` 只认 `pairing` / `agents` 两个名字，其余一律落默认页 —— **地址栏不是命令通道**，
  宁可落首页也不乱跳。新增落点必须同时改代码和这条审计的口径表。
- 主域名与 `www.` 在同一个 vhost 里，两个都覆盖；`app.karma-network.ai` 只补了查询串，没做 301 收口
  （它是旧域名，302 保留也无害）。
- vhost 仍未纳入仓库（历史口径：“发过的产物”）；本轮没有改变这一点，只在审计里记明。
- 主网（`karma-network.ai` 上的主网开关 / 真实资金）未动。

## 7. 追加（同日）：入口不再“跳转”——地址栏停在 `/console`

**用户复问**：「为什么操作台的域名还是 `https://karma-network.ai/console/pages/cyber/index.html`」。
§3 那张表是 F1/F2 修完的状态：入口是 `return 302`，页面出得来，但**地址栏跟着 302 走**，
用户看到的就是长路径。口径要求的是地址栏停在 `https://karma-network.ai/console`。
**本节取代 §3 里那张 302 表。**

**为什么不能只把 302 换成 alias**：页面里的 `<script src>` / `<link href>` 全是相对 `../../` 写的，
而相对路径怎么解析看的是**地址栏深度**：只有落在 `/console/pages/cyber/` 上，`../../` 才指得回 `/console/`；
地址栏收成 `/console` 以后，`../../` 会一路指到站点根，整页资源全 404。
所以短入口这一条路由给页面钉一个跟原来**完全一样**的 `<base href="/console/pages/cyber/">`，资源解析口径不变。

控制台代码、`?v=` 打戳门禁（`scripts/stamp_console_assets.py`）、`apps/console/**` 下的既有用例
**一个字都没改** —— 打戳工具本来就是按“页面目录”解析这些相对引用的，和 `base` 是同一个口径。
重写 45 条资源地址会连带改到打戳工具与 10 多条用例断言（那些断言钉的就是相对形式），收益不值得，风险反而更大。

**改法**（`/www/server/panel/vhost/nginx/karma-site.conf`）：

```nginx
location = /console {
    default_type text/html;
    alias /www/wwwroot/console/pages/cyber/index.html;
    add_header Cache-Control "no-cache";
    sub_filter '<head>' '<head><base href="/console/pages/cyber/">';
    sub_filter_once on;
}
location = /console/ {
    rewrite ^ /console last;
}
```

两个坑都是线上实测踩出来的（不是推演）：

- **`default_type` 必须点名**：`alias` 到文件时内容类型按 URI 判，`/console` 没有扩展名，
  默认就落到 http 块里的 `application/octet-stream` —— 浏览器会当**下载**而不是渲染，
  而 `sub_filter` 的默认类型是 `text/html`，不匹配就不改写。第一版就是这个症状：200 但 base 没注入。
- **`/console/` 不能照抄 `alias`**：URI 以 `/` 结尾时索引模块会往 alias 的文件路径后面再拼一个 `index.html`，
  报 `.../index.htmlindex.html is not a directory` → 500（`/www/wwwlogs/nginx_error.log`）。
  改成内部重写回 `/console`，不发外部跳转，地址栏保持用户输入的样子。

### 线上实测（改后，VPS 本机 curl，不跟跳转）

```
/console                            200  ct=text/html        （无 Location）
/console/                           200  ct=text/html        （无 Location）
/console?view=agents                200  ct=text/html        查询串原样在位
/consle  /consle/                   301  -> https://karma-network.ai/console
/console/pages/cyber/index.html     200  ct=text/html        （长路径照旧可用）
/health                             200  ct=application/json
/console/index.html                 200  ct=text/html        （旧 shim，不再是入口）
```

字节级校验（证明没有别的东西被动过）：

```
长路径响应            == /www/wwwroot/console/pages/cyber/index.html   identical
/console 响应          == 发布文件 + 恰好 1 个 <base> 标签（去掉后逐字节相同）127882 = 127847 + 35
/console/ 响应         同上
/console/scripts/*.js  /console/styles/*.css  == 发布物   identical（没有被改写）
```

浏览器口径的资源可达性：把短入口那份 HTML 里 42 条本地 js/css/png 引用按 `base` 解析一遍，
逐条回源 —— **0 条不可达**。改前（302 长路径）与改后解析结果一致。

**回滚**：`/www/server/panel/vhost/nginx/karma-site.conf.bak-console-short2-20261013-040932`
（本轮之前那一版，即 §3 的 302 版；第一版尝试留的 `.bak-console-short-20261013-040827` 也在）。
换回去 + `nginx -s reload` 即可。vhost 仍未纳入仓库（§6 的口径不变），
但 `karma-web-deploy` 不写 nginx 配置，所以下次部署不会冲掉这笔改动。

### 顺带发现（当日已修，见 #288）

- `apps/console/styles/cyber-console.css` 里 `background-image: url("../../assets/earth-texture.jpg")`：
  CSS 里的相对地址是相对**样式表自己**解析的，`/console/styles/` 往上两级是站点根，
  所以这条一直指向 `/assets/earth-texture.jpg`（线上 **404**）。与本轮入口改动无关
  （改前改后是同一条 URL），是操作台背景纹理一直没加载。要修就得改这份 CSS 并重跑打戳脚本，单独一轮做。**（2026-10-13 当天已单独开一轮修掉：见 #288 与 `2026-10-13-console-daily-review.md`；并已固化成门禁 `scripts/check_console_assets.py` + 单测，防这类「引用落不到文件」再回来。）**

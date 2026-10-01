# 部署流水线与分支保护

这份文档描述 `main` 上的代码**怎么变成线上正在跑的东西**，以及这条链路上每一道锁
为什么在那儿。

## 之前是什么样（2026-10-01 之前）

- `.github/workflows/deploy-vps.yml` 的 `deploy` job 挂在 `vars.VPS_DEPLOY_ENABLED`
  上，而仓库里**既没有这个 variable，也没有任何一个 `VPS_*` secret**。
  结果：这个 job **永远 skip，却显示绿色**。看板上一片绿，实际每次发布都是人手工
  在服务器上跑 `ci-deploy.sh`。
- `main` **没有分支保护**（`GET /branches/main/protection` 返回 404）。
- 仓库是 **public**，密钥扫描和 push protection 都是关的。
- `ci-deploy.sh` 最后一行是 `exec`，跑完就没了下文：没有任何东西证明「线上真的换了版本」。

## 现在是什么样

```
push 到 main
   │
   ├─ Deploy to VPS / test           单元测试 + app 导入烟测
   │
   └─ Deploy to VPS / deploy
        │  1. 先检查 VPS_SSH_KEY / VPS_HOST / VPS_SSH_USER 齐不齐，缺了就明确报错
        │     （宁可红一次，也不要一个永远 skip 的假绿灯）
        │  2. SSH 到服务器
        │        │
        │        └─ 这把 key 在 authorized_keys 里带 forced command：
        │             command="/usr/local/bin/karma-ci-deploy",no-port-forwarding,
        │             no-agent-forwarding,no-X11-forwarding,no-pty,no-user-rc
        │           客户端发什么命令都会被忽略，只能跑那个入口脚本。
        │           入口把 deploy/vps/ci-deploy.sh 拷到临时文件再执行
        │           （ci-deploy.sh 自己会 git pull 覆盖自己）。
        │              │
        │              └─ ci-deploy.sh → `karma deploy`：
        │                   拉代码 → alembic 迁移 → 发布静态站/操作台 → 重建容器 →
        │                   健康检查 → **自证 HEAD == origin/main 且已跟踪文件无改动**
```

最后那一步自证是关键：CI 绿的含义从「脚本没报错」变成「服务器上跑的确实是这次提交」。

## 仓库需要哪些配置

Settings → Secrets and variables → Actions：

| 类型 | 名字 | 值 | 说明 |
|---|---|---|---|
| Variable | `VPS_DEPLOY_ENABLED` | `true` | 不开就是 skip（今天已是 `true`） |
| Variable | `VPS_HOST` | `47.82.74.68` | 服务器 IP，不是秘密 |
| Variable | `VPS_SSH_USER` | `root` | 登录用户 |
| **Secret** | `VPS_SSH_KEY` | 见下 | **CI 专用私钥，带 forced command** |

变量（variable）不是秘密，可以用 API 设；secret 必须用 libsodium 加密后提交，
**只有仓库管理员能在网页上贴**。

## CI 那把私钥

### 它是什么

`/root/.ssh/karma_ci_deploy_ed25519`（服务器上，`600`）。对应的公钥在
`/root/.ssh/authorized_keys` 里，那一行带 `command="..."` 限制 ——
**这把 key 拿不到 shell**，只能触发 `/usr/local/bin/karma-ci-deploy`。

实测（2026-10-01）：用它 SSH 过去发 `echo I-AM-A-SHELL; id`，返回的是部署日志，
不是 shell。

### 把私钥交给 GitHub

`VPS_SSH_KEY` 这个 secret 需要仓库管理员在网页上填。私钥**不经过任何第三方**，
直接在服务器上打印、复制、粘贴：

```bash
# 在服务器上执行，把输出整段（含 BEGIN/END 两行）贴进 GitHub secret 的值里
cat /root/.ssh/karma_ci_deploy_ed25519
```

粘贴位置：Settings → Secrets and variables → Actions → Secrets →
New repository secret → 名字 `VPS_SSH_KEY`。

**不要**把这个私钥贴进 issue、聊天、或提交进仓库。

### 轮换

```bash
# 1) 服务器上换一把
ssh-keygen -t ed25519 -N '' -C 'karma-ci-deploy(forced-cmd)' -f /root/.ssh/karma_ci_deploy_ed25519.new
# 2) 把 authorized_keys 里那条换成新公钥（command= 前缀和选项保持不变）
# 3) 把新的私钥贴到 GitHub secret VPS_SSH_KEY
# 4) 从 authorized_keys 删掉旧公钥
```

轮换后跑一次 `Deploy to VPS`（Actions → Deploy to VPS → Run workflow）确认能通。

### 入口脚本为什么在仓库外

`/usr/local/bin/karma-ci-deploy` 是 `deploy/vps/ci-deploy-entry.sh` 装上去的。
放在仓库外，是因为仓库会被 `git pull` 覆盖，而 sshd 指向的东西不该在部署过程中
被就地改写。仓库里那份是唯一事实来源，安装命令写在脚本头部注释里。

## 分支保护（`main`）

2026-10-01 起：

- 必需的检查：`pytest`、`guard`、`security-gates`、`visibility-guard`、`ops-scripts`
- 禁止强推（`allow_force_pushes=false`）、禁止删除分支（`allow_deletions=false`）
- `enforce_admins=false`：仓库管理员**仍然可以直接 push**（单人维护时的现实选择）

想再紧一档就把 `enforce_admins` 打开，或加上「必须走 PR + 1 个批准」——
那会改变你的日常流程，所以留给你决定。

改法（需要管理员 PAT）：

```bash
curl -X PUT -H "Authorization: Bearer $TOKEN" \
     -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/AtoB101/Karma/branches/main/protection \
     -d '{"required_status_checks":{"strict":false,"contexts":["pytest","guard","security-gates","visibility-guard","ops-scripts"]},"enforce_admins":true,"required_pull_request_reviews":null,"restrictions":null,"allow_force_pushes":false,"allow_deletions":false}'
```

## 密钥扫描

public 仓库免费。2026-10-01 起开启：

- Secret scanning：`enabled`
- Secret scanning push protection：`enabled`

push protection 会在 push 时就拦下看起来像凭证的内容。这个仓库是公开的，
所以这一条的价值比平时更高：任何一次「不小心把 .env 里的东西粘进代码」都会
在离开本机之前被拦住。

## 怎么确认这条流水线真的通了

1. 贴好 `VPS_SSH_KEY`；
2. Actions → Deploy to VPS → Run workflow（或推一个空提交到 main）；
3. 看日志末尾有没有 `deployed revision verified: <sha>`，且这个 sha 等于本次提交；
4. 在服务器上对一下：`git -C /opt/karma/repo rev-parse HEAD`。

如果第 3 步红在 "Check deploy credentials are present"，说明 secret 还没贴。
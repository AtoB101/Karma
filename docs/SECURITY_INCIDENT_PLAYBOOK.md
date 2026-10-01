# Security Incident Playbook

This playbook defines the minimum response workflow for security incidents during public beta.

## 1) Trigger Conditions

Treat any of the following as an incident trigger:

- Repeated `auth_failure_spike` alerts from `/v1/security/ops/alerts`
- Sustained `rate_limit_spike` with customer-facing 429 impact
- `private_runtime_error_rate` alert at `high` or `critical`
- baseline drift alerts (`*_baseline_drift`) sustained across consecutive windows
- Any confirmed unauthorized write action, credential leak, or data integrity violation

## 2) Severity Levels

- **SEV-1 (critical)**: active compromise, unauthorized settlement/state transition, widespread outage with security implications.
- **SEV-2 (high)**: strong attack signals or persistent degradation that could lead to compromise.
- **SEV-3 (medium)**: suspicious trend requiring containment and monitoring.

## 2.1) Alert Escalation Mapping

Use `/v1/security/ops/alerts` response fields:

- `escalation.level = page`: immediate on-call paging (treat as SEV-1/SEV-2 depending blast radius).
- `escalation.level = watch`: active monitoring with named owner (SEV-2/SEV-3).
- `suppressed_alert_count > 0`: recurring signal is still active; do not treat as resolved.

## 3) Immediate Response (0-15 minutes)

1. Open incident channel and assign roles:
   - Incident Commander
   - API/Runtime Operator
   - Forensics Recorder
2. Capture immutable context:
   - Request IDs from security audit logs
   - Affected endpoints, actor IDs, and time window
   - Current `/v1/security/ops/alerts` snapshot
3. Execute first containment:
   - Rotate exposed `AUTH_API_KEYS`
   - Increase rate-limit strictness if abuse is active
   - Promote or roll back threshold policy via policy center (`/v1/security/policies/*`)
   - Temporarily disable risky public entrypoints if required

## 4) Investigation and Containment

- Correlate `security_write_audit` logs with auth failures and 429 spikes.
- Validate whether private runtime failures are dependency/network or malicious traffic amplification.
- If compromise suspected:
  - Force key rotation (`APP_SECRET_KEY`, runtime keys, API keys)
  - Revoke affected agent credentials
  - Isolate compromised workers/services

## 5) Recovery

- Restore services incrementally with heightened monitoring.
- Confirm:
  - auth failure volume normalized
  - 429 ratios normalized
  - private runtime error rate below threshold
- Confirm `suppressed_alert_count == 0` for at least one full alert window after mitigation.
- Run `scripts/public-beta-security-gate.sh` before declaring incident resolved.

## 6) Post-Incident Review

Within one cycle after resolution:

- Publish timeline (trigger, detection, containment, recovery)
- Record root cause and blast radius
- Add concrete preventive actions with owners
- Update `docs/SECURITY_RELEASE_GATES.md` and this playbook if controls changed

---

## 7) Log Retention and Query Access (gate C3)

出事时最贵的是时间。这一节把「日志留多久」和「出事时敲哪条命令」写死，
闸门 `C3a`/`C3b`/`C3c` 分别校验它：容器日志上限、journald 留存是否**显式**写死、本节是否存在。

### 留多久

| 日志 | 落在哪 | 上限 | 保留窗口 |
|---|---|---|---|
| 容器 stdout/stderr（`karma-api` / `karma-postgres` / `karma-redis`） | `/var/lib/docker/containers/*/*-json.log` | `max-size=20m` × `max-file=5`（每容器 100 MB） | 写满即滚，通常覆盖最近数天到数周 |
| 系统日志（journald） | `/var/log/journal`（`Storage=persistent`） | `SystemMaxUse` / `SystemKeepFree` / `MaxRetentionSec` 显式写死 | ≥ 90 天 |
| 安全审计（数据库 `security_audit` 等） | PostgreSQL | 随快照 | 与数据库同寿命，按备份策略 |

**90 天**是刻意与密钥轮换周期同口径（见 [`KEY_ROTATION.md`](./KEY_ROTATION.md)）：
一次季度轮换之后，仍能回查这期间发生过的鉴权 / 限流 / 状态机事件。

### 出事时敲什么

```bash
# 最近 15 分钟的 API 日志
docker logs --since 15m karma-api 2>&1 | tail -200

# 按 request_id 追一次请求（C1/C2 保证每个敏感写都带 actor+path+method+status+request_id）
docker logs --since 2h karma-api 2>&1 | grep -F '<request_id>'

# 系统日志按时间段 / 单元查
journalctl --since '2 hours ago' --no-pager | tail -200
journalctl -u docker --since '2026-10-01 00:00' --until '2026-10-01 06:00' --no-pager

# 先看磁盘占用（日志类告警出现时第一步）
du -sh /var/lib/docker/containers/*/*-json.log | sort -h | tail
journalctl --disk-usage
```

修改留存口径时：改 `/etc/systemd/journald.conf` → `systemctl restart systemd-journald`
→ 把新值同步回上表。别让表和实际配置分叉。

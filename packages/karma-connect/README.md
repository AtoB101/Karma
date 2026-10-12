# karma-connect

One command that wires the **Karma MCP server** into every agent host on this machine.

```bash
pip install ./packages/karma-connect
# or, without cloning the repo:
pip install "karma-connect @ git+https://github.com/AtoB101/Karma@main#subdirectory=packages/karma-connect"
karma-connect detect
karma-connect install
```

Not on PyPI yet (`pip install karma-connect` returns 404); see
[`docs/mcp/karma-mcp-integration.md`](../../docs/mcp/karma-mcp-integration.md).

No JSON editing, no config file archaeology. It finds the hosts you already have
and writes one named server entry into each.

## Which server it wires

`karma-mcp-server` (`packages/karma-mcp-server`) - the thin access layer that only
ever holds `KARMA_RUNTIME_KEY`. The older `karma-mcp` package is **not** used: it
wanted `KARMA_PRIVATE_KEY` injected into the MCP process, which the security audit
retired, and `karma-mcp-server` refuses to start when private key material is in its
environment. So `install` refuses `--env KARMA_PRIVATE_KEY=...` (or any mnemonic key)
instead of writing a server that can never boot.

`KARMA_RUNTIME_URL` defaults to the public node (`https://karma-network.ai`), so a
fresh install needs no `--env` at all. Everything else the agent needs arrives when
the owner approves the pairing.

## What it touches

| host | config | key |
|---|---|---|
| Codex CLI | `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`) | `[mcp_servers.karma]` |
| Claude Code | `~/.claude.json` | `mcpServers.karma` |
| Cursor | `~/.cursor/mcp.json` | `mcpServers.karma` |
| Muse Code (Meta) | `${XDG_CONFIG_HOME:-~/.config}/muse/settings.json` | `mcpServers.karma` |
| OpenClaw | `$OPENCLAW_STATE_DIR/openclaw.json` (default `~/.openclaw/openclaw.json`) | `mcp.servers.karma` |
| VS Code | `<workspace>/.vscode/mcp.json` (only with `--workspace`) | `servers.karma` |

Only that one entry is touched; every other line is preserved. Running install
twice changes nothing the second time.

## Gotchas it handles for you

- **Muse Code** wants `"type": "stdio"` (its docs page says `transport`, the binary
  does not) plus `schema_version: 1`, and it drops the whole MCP block if
  `mcp_servers` and `mcpServers` ever appear together. This tool only writes
  `mcpServers`.
- **Codex** keeps MCP servers in TOML tables, not JSON, so the writer replaces just
  the `[mcp_servers.karma]` block and leaves your `model`, plugins and marketplaces
  alone.
- **OpenClaw** nests under `mcp.servers`, not `mcpServers`.

## Commands

- `karma-connect detect` - which hosts exist here, and where their config lives
- `karma-connect install [--host codex,muse] [--dry-run]` - write the entry
- `karma-connect doctor` - is `karma-mcp-server` reachable, is every config readable, is this machine paired yet
- `karma-connect sign-check` - print the per-request signature this machine would send

## After installing

1. Restart the agent host so it reloads MCP servers.
2. Have the agent call `karma_connect` (`agent_name` = whatever it calls itself). It
   prints a `user_code` and a `verification_uri` - open that link in Karma Console,
   check the `agent_fingerprint` on the card matches the one the agent showed you,
   set the limits, and approve.
3. Have the agent call `karma_connect_claim`. Approval **is** activation, so the
   credentials come back directly - there is no 8-character code to relay.
4. Credentials land in `~/.karma/agent.env` (0600). Nothing secret travels through chat.

The 8-character handoff code still exists as a fallback for machines that cannot
generate a local agent key, and the console can add an email-receipt gate as a third
lock when the approval carries `notify_email`.

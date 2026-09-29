# karma-connect

One command that wires the **Karma MCP server** into every agent host on this machine.

```bash
pip install ./packages/karma-connect
karma-connect detect
karma-connect install --env KARMA_RPC_URL=https://mainnet.base.org --env KARMA_CONTRACT=0x...
```

No JSON editing, no config file archaeology. It finds the hosts you already have
and writes one named server entry into each.

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
- `karma-connect doctor` - is `karma-mcp` on PATH, are credentials present, is every config readable

## After installing

1. Restart the agent host so it reloads MCP servers.
2. Have the agent call `karma_pairing_start`; approve it in Karma Console.
3. Read the 8-character handoff code back to the agent; it calls `karma_pairing_claim`.
4. Credentials land in `~/.karma/agent.env` (0600). Nothing secret travels through chat.

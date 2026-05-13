# OpenClaw ↔ Karma (MCP bridge)

Use the **`karma-openclaw`** package: it runs a **stdio MCP server** that exposes Karma **public HTTP** tools (capacity, evidence bundles, …).

```bash
pip install -e ../../packages/karma-openclaw
export KARMA_RUNTIME_URL=http://localhost:8000
export KARMA_API_KEY=your-api-key
karma-openclaw-mcp
```

Register this command in OpenClaw’s **MCP bridge** (stdio transport). See **`packages/karma-openclaw/README.md`**.

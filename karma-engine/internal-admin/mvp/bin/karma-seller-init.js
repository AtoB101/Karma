#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

function writeFileSafe(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, "utf-8");
}

function main() {
  const arg = process.argv[2] || "";
  if (arg === "-h" || arg === "--help") {
    console.log("Usage: karma-seller-init [target-dir]");
    console.log("Creates a minimal paid-tool seller starter project.");
    process.exit(0);
  }
  const targetDir = arg || "karma-seller-starter";
  const out = path.resolve(process.cwd(), targetDir);
  if (fs.existsSync(out) && fs.readdirSync(out).length > 0) {
    console.error(`Target directory is not empty: ${out}`);
    process.exit(1);
  }

  writeFileSafe(
    path.join(out, "package.json"),
    JSON.stringify(
      {
        name: "karma-seller-starter",
        version: "0.1.0",
        private: true,
        scripts: {
          start: "node index.js",
        },
      },
      null,
      2
    ) + "\n"
  );

  writeFileSafe(
    path.join(out, ".env.example"),
    [
      "TC_GATEWAY_URL=http://127.0.0.1:8822",
      "TC_USER_ID=seller-demo-user",
      "TC_TOKEN=USDC",
      "TC_PRICE=0.01",
      "TC_DEFAULT_SYMBOL=BTCUSDT",
      "",
    ].join("\n")
  );

  writeFileSafe(
    path.join(out, "index.js"),
    `#!/usr/bin/env node
"use strict";
const { wrapTool } = require("../karma-wrap-tool");

async function priceTool({ symbol }) {
  return { symbol, note: "your tool output goes here", at: new Date().toISOString() };
}

async function main() {
  const wrapped = wrapTool({
    gatewayBaseUrl: process.env.TC_GATEWAY_URL || "http://127.0.0.1:8822",
    userId: process.env.TC_USER_ID || "seller-demo-user",
    token: process.env.TC_TOKEN || "USDC",
    price: process.env.TC_PRICE || "0.01",
    tool: priceTool,
  });

  const symbol = process.argv[2] || process.env.TC_DEFAULT_SYMBOL || "BTCUSDT";
  const result = await wrapped({ symbol });
  console.log(JSON.stringify(result, null, 2));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
`
  );

  writeFileSafe(
    path.join(out, "README.md"),
    `# Karma Seller Starter

## Quick start

1. Copy env:
   \`cp .env.example .env\`
2. Start Karma gateway in another terminal.
3. Run first paid call:
   \`node index.js BTCUSDT\`
`
  );

  console.log(`Seller starter created at: ${out}`);
}

main();

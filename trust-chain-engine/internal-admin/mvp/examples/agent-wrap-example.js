#!/usr/bin/env node
"use strict";

const { wrapTool } = require("../trustchain-wrap-tool");

async function fakePriceTool({ symbol }) {
  return { symbol, hint: "price comes from paid gateway", at: new Date().toISOString() };
}

async function main() {
  const gatewayBaseUrl = process.env.TC_GATEWAY_URL || "http://127.0.0.1:8822";
  const wrapped = wrapTool({
    gatewayBaseUrl,
    tool: fakePriceTool,
    price: "0.01",
    token: "USDC",
    userId: process.env.TC_USER_ID || "agent-author-demo-user",
  });

  const result = await wrapped({
    symbol: process.argv[2] || "BTCUSDT",
    metadata: { source: "agent-wrap-example" },
  });

  console.log(JSON.stringify(result, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

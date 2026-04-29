#!/usr/bin/env node
"use strict";

const { wrapTool } = require("../trustchain-wrap-tool");

async function sellerTool({ symbol }) {
  // Replace with your real API logic.
  return {
    symbol,
    payload: "replace-with-real-seller-response",
    generatedAt: new Date().toISOString(),
  };
}

async function main() {
  const gatewayBaseUrl = process.env.TC_GATEWAY_URL || "http://127.0.0.1:8822";
  const userId = process.env.TC_USER_ID || "seller-demo-user";
  const symbol = process.argv[2] || "BTCUSDT";

  const wrapped = wrapTool({
    tool: sellerTool,
    gatewayBaseUrl,
    userId,
    token: "USDC",
    price: "0.01",
  });

  const result = await wrapped({ symbol });
  console.log(JSON.stringify(result, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

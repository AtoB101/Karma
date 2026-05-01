#!/usr/bin/env node
"use strict";

/**
 * Minimal private wrapper to monetize agent tools via Karma paid endpoint.
 *
 * Usage pattern:
 *   const wrapped = wrapTool({
 *     tool: async ({ symbol }) => ({ symbol, value: 123 }),
 *     symbolResolver: (input) => input.symbol,
 *     gatewayBaseUrl: "http://127.0.0.1:8822",
 *     userId: "agent-owner-01",
 *   });
 *   const result = await wrapped({ symbol: "BTCUSDT" });
 */

function required(name, value) {
  if (!value) {
    throw new Error(`Missing required option: ${name}`);
  }
}

async function requestPaidSettlement({ gatewayBaseUrl, symbol, userId }) {
  const url = `${gatewayBaseUrl.replace(/\/+$/, "")}/api/v1/price-paid?symbol=${encodeURIComponent(symbol)}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ userId }),
  });
  const payload = await resp.json();
  if (!resp.ok || !payload.ok) {
    throw new Error(payload.error || `Paid endpoint failed (${resp.status})`);
  }
  return payload;
}

function wrapTool(options) {
  required("tool", options?.tool);
  required("gatewayBaseUrl", options?.gatewayBaseUrl);

  const tool = options.tool;
  const userId = options.userId || "agent-user";
  const symbolResolver =
    options.symbolResolver ||
    ((input) => input?.symbol || input?.pair || "BTCUSDT");

  return async function wrappedTool(input, context = {}) {
    const symbol = String(symbolResolver(input, context) || "").trim().toUpperCase();
    if (!symbol) {
      throw new Error("symbolResolver returned empty symbol");
    }

    // 1) Execute tool logic (service delivery)
    const serviceOutput = await tool(input, context);

    // 2) Trigger paid settlement and fetch quote proof
    const settlement = await requestPaidSettlement({
      gatewayBaseUrl: options.gatewayBaseUrl,
      symbol,
      userId,
    });

    return {
      ok: true,
      schemaVersion: "karma.mvp.wrap-tool.result.v1",
      symbol,
      serviceOutput,
      monetization: {
        token: options.token || "ETH(test)",
        priceLabel: options.price || "per-call",
        chargedWei: settlement.settlement.chargedWei,
        txHash: settlement.settlement.txHash,
        chainId: settlement.settlement.chainId,
        beforeBalanceEth: settlement.settlement.beforeBalanceEth,
        afterBalanceEth: settlement.settlement.afterBalanceEth,
      },
      marketData: settlement.market,
      callProof: {
        callId: settlement.callId,
        completedAt: settlement.completedAt,
      },
    };
  };
}

module.exports = { wrapTool };

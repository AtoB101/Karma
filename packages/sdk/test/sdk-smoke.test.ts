import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  KarmaPublicSdk,
  agentExecutionExtensionFromHashes,
  apiExecutionExtensionFromHashes,
  mcpExecutionExtensionFromHashes,
} from "../src/index.js";

const BASE = "https://runtime.example";

type Call = { url: string; method: string; body?: string };

function captureFetch(): { calls: Call[]; stub: ReturnType<typeof vi.fn> } {
  const calls: Call[] = [];
  const stub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? init.body : undefined;
    calls.push({ url, method, body });

    if (url.includes("/v1/progress/task/") && url.includes("timeout-confirm")) {
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.includes("/v1/progress/task/") && !url.includes("timeout-confirm")) {
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ stub: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", stub);
  return { calls, stub };
}

describe("KarmaPublicSdk HTTP surface (smoke)", () => {
  let calls: Call[];
  let stub: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    const c = captureFetch();
    calls = c.calls;
    stub = c.stub;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("strips trailing slash from runtimeUrl", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: `${BASE}/` });
    await sdk.getCapacity("id-1");
    expect(calls[0]?.url).toBe(`${BASE}/v1/capacity/id-1`);
  });

  it("sends X-Karma-Api-Key when apiKey is set", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE, apiKey: "secret" });
    await sdk.getCapacity("x");
    expect(stub).toHaveBeenCalled();
    const [, init] = stub.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Karma-Api-Key"]).toBe("secret");
    expect(headers["content-type"]).toBe("application/json");
  });

  it("encodes path parameters", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE });
    await sdk.verifyVoucher("v/1", "seller");
    expect(calls[0]?.url).toContain(encodeURIComponent("v/1"));
  });

  it("lockUsdc posts amount JSON", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE });
    await sdk.lockUsdc("buyer", 12.5);
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.url).toBe(`${BASE}/v1/capacity/buyer/lock`);
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({ amount: 12.5 });
  });

  it("createVoucher posts body", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE });
    await sdk.createVoucher({ foo: 1 });
    expect(calls[0]?.url).toBe(`${BASE}/v1/vouchers`);
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({ foo: 1 });
  });

  it("verifyVoucher includes optional expected_amount", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE });
    await sdk.verifyVoucher("vid", "sid", 99);
    expect(calls[0]?.url).toContain("/v1/vouchers/vid/verify");
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({ seller_identity_id: "sid", expected_amount: 99 });
    calls.length = 0;
    await sdk.verifyVoucher("vid", "sid");
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({ seller_identity_id: "sid" });
  });

  it("acceptVoucher posts seller_identity_id", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE });
    await sdk.acceptVoucher("v1", "seller");
    expect(calls[0]?.url).toContain("/v1/vouchers/v1/accept");
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({ seller_identity_id: "seller" });
  });

  it("settlement lifecycle URLs", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE });
    await sdk.createSettlement({ task_id: "t" });
    await sdk.markSettlementPending("t%20x");
    await sdk.lockSettlement("t%20x", "worker");
    await sdk.autoArbitrate("t1");
    await sdk.startTaskExecution("t1");
    await sdk.submitDelivery("t1");
    await sdk.openDispute("t1", "bad");
    await sdk.partialSettlement("t1", 40, "partial reason");
    await sdk.regretTask("t1", { buyerIdentityId: "b", reason: "r" });

    expect(calls[0]?.url).toBe(`${BASE}/v1/settlement/create`);
    expect(calls[1]?.url).toBe(`${BASE}/v1/settlement/${encodeURIComponent("t%20x")}/pending`);
    expect(calls[2]?.url).toBe(`${BASE}/v1/settlement/${encodeURIComponent("t%20x")}/lock`);
    expect(calls[3]?.url).toBe(`${BASE}/v1/settlement/t1/auto-arbitrate`);
    expect(calls[4]?.url).toBe(`${BASE}/v1/settlement/t1/start`);
    expect(calls[5]?.url).toBe(`${BASE}/v1/settlement/t1/submit`);
    expect(calls[6]?.url).toBe(`${BASE}/v1/settlement/t1/dispute`);
    expect(calls[7]?.url).toBe(`${BASE}/v1/settlement/t1/partial`);
    expect(calls[8]?.url).toBe(`${BASE}/v1/settlement/t1/regret`);

    expect(JSON.parse(calls[6]?.body ?? "{}")).toEqual({ reason: "bad" });
    expect(JSON.parse(calls[7]?.body ?? "{}")).toEqual({
      settled_value_percent: 40,
      reason: "partial reason",
    });
    expect(JSON.parse(calls[8]?.body ?? "{}")).toEqual({
      buyer_identity_id: "b",
      reason: "r",
    });
  });

  it("openDispute omits empty reason", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE });
    await sdk.openDispute("t1", "");
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({});
  });

  it("acceptTask chains create, pending, lock", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE });
    await sdk.acceptTask({
      taskId: "task-a",
      buyerIdentityId: "buyer",
      sellerIdentityId: "seller",
      voucherId: "vouch",
      escrowAmount: 100,
      currency: "EUR",
    });
    expect(calls).toHaveLength(3);
    expect(calls[0]?.url).toBe(`${BASE}/v1/settlement/create`);
    expect(calls[1]?.url).toBe(`${BASE}/v1/settlement/task-a/pending`);
    expect(calls[2]?.url).toBe(`${BASE}/v1/settlement/task-a/lock`);
    expect(JSON.parse(calls[0]?.body ?? "{}")).toMatchObject({
      task_id: "task-a",
      client_agent_id: "buyer",
      escrow_amount: 100,
      currency: "EUR",
      voucher_id: "vouch",
    });
    expect(JSON.parse(calls[2]?.body ?? "{}")).toEqual({ worker_agent_id: "seller" });
  });

  it("receipts, progress, bundles", async () => {
    const sdk = new KarmaPublicSdk({ runtimeUrl: BASE });
    await sdk.submitExecutionReceipt({ receipt_id: "r1" });
    await sdk.submitProgress({ task_id: "t" });
    await sdk.confirmProgress("pr-1");
    const list = await sdk.listProgressForTask("t/p");
    await sdk.timeoutConfirmStaleProgress("t/p", 48);
    await sdk.submitEvidenceBundle({ bundle_id: "b1" });

    expect(calls[0]?.url).toBe(`${BASE}/v1/receipts`);
    expect(calls[1]?.url).toBe(`${BASE}/v1/progress`);
    expect(calls[2]?.url).toBe(`${BASE}/v1/progress/pr-1/confirm`);
    expect(calls[3]?.url).toBe(`${BASE}/v1/progress/task/${encodeURIComponent("t/p")}`);
    expect(calls[4]?.url).toContain(
      `${BASE}/v1/progress/task/${encodeURIComponent("t/p")}/timeout-confirm?`,
    );
    expect(calls[4]?.url).toContain("max_pending_hours=48");
    expect(calls[5]?.url).toBe(`${BASE}/v1/bundles`);
    expect(Array.isArray(list)).toBe(true);
  });
});

describe("P1 extension hash builders", () => {
  it("builds api / mcp / agent extension objects", () => {
    const h = "a".repeat(64);
    expect(
      apiExecutionExtensionFromHashes({
        requestHash: h,
        responseHash: h,
        httpStatusCode: 200,
        latencyMs: 5,
      }),
    ).toEqual({
      kind: "api",
      request_hash: h,
      response_hash: h,
      http_status_code: 200,
      latency_ms: 5,
    });
    expect(
      mcpExecutionExtensionFromHashes({
        mcpServerId: "s",
        mcpToolName: "t",
        traceHash: h,
        resultHash: h,
      }),
    ).toMatchObject({ kind: "mcp", mcp_server_id: "s", mcp_tool_name: "t" });
    expect(
      agentExecutionExtensionFromHashes({
        modelUsed: "m",
        toolCallsHash: h,
        stepLogHash: h,
        runtimeTraceHash: h,
      }),
    ).toMatchObject({ kind: "agent", model_used: "m" });
  });
});

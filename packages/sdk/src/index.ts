/**
 * @karma-network/sdk — P0–P1 HTTP surface for Karma public API (TypeScript).
 * Mirrors Python `sdk.KarmaClient` lock / capacity / voucher / settlement / receipts
 * and exposes P1 typed receipt extension builders (hash-in / JSON-out).
 */

export type Json = Record<string, unknown>;

/** P1 — typed execution receipt extension (matches OpenAPI / Python schemas). */
export type ApiExecutionReceiptExtension = {
  kind: "api";
  request_hash: string;
  response_hash: string;
  http_status_code: number;
  latency_ms: number;
  error_code?: string | null;
};

export type McpExecutionReceiptExtension = {
  kind: "mcp";
  mcp_server_id: string;
  mcp_tool_name: string;
  trace_hash: string;
  result_hash: string;
};

export type AgentExecutionReceiptExtension = {
  kind: "agent";
  model_used: string;
  tool_calls_hash: string;
  step_log_hash: string;
  runtime_trace_hash: string;
};

export type ExecutionReceiptExtension =
  | ApiExecutionReceiptExtension
  | McpExecutionReceiptExtension
  | AgentExecutionReceiptExtension;

/**
 * Build ``kind: api`` extension when the caller already has lowercase hex SHA-256 digests
 * (64 chars). Keeps the TS SDK free of crypto so it works in browsers without polyfills.
 */
export function apiExecutionExtensionFromHashes(params: {
  requestHash: string;
  responseHash: string;
  httpStatusCode: number;
  latencyMs: number;
  errorCode?: string | null;
}): ApiExecutionReceiptExtension {
  return {
    kind: "api",
    request_hash: params.requestHash,
    response_hash: params.responseHash,
    http_status_code: params.httpStatusCode,
    latency_ms: params.latencyMs,
    error_code: params.errorCode ?? undefined,
  };
}

export function mcpExecutionExtensionFromHashes(params: {
  mcpServerId: string;
  mcpToolName: string;
  traceHash: string;
  resultHash: string;
}): McpExecutionReceiptExtension {
  return {
    kind: "mcp",
    mcp_server_id: params.mcpServerId,
    mcp_tool_name: params.mcpToolName,
    trace_hash: params.traceHash,
    result_hash: params.resultHash,
  };
}

export function agentExecutionExtensionFromHashes(params: {
  modelUsed: string;
  toolCallsHash: string;
  stepLogHash: string;
  runtimeTraceHash: string;
}): AgentExecutionReceiptExtension {
  return {
    kind: "agent",
    model_used: params.modelUsed,
    tool_calls_hash: params.toolCallsHash,
    step_log_hash: params.stepLogHash,
    runtime_trace_hash: params.runtimeTraceHash,
  };
}

export interface KarmaSdkOptions {
  runtimeUrl: string;
  apiKey?: string;
  timeoutMs?: number;
}

export class KarmaPublicSdk {
  readonly runtimeUrl: string;
  readonly apiKey: string;
  readonly timeoutMs: number;

  constructor(opts: KarmaSdkOptions) {
    this.runtimeUrl = opts.runtimeUrl.replace(/\/$/, "");
    this.apiKey = opts.apiKey ?? "";
    this.timeoutMs = opts.timeoutMs ?? 120_000;
  }

  private headers(): HeadersInit {
    const h: Record<string, string> = { "content-type": "application/json" };
    if (this.apiKey) h["X-Karma-Api-Key"] = this.apiKey;
    return h;
  }

  async lockUsdc(identityId: string, amount: number): Promise<Json> {
    const r = await fetch(`${this.runtimeUrl}/v1/capacity/${encodeURIComponent(identityId)}/lock`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({ amount }),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`lockUsdc failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async getCapacity(identityId: string): Promise<Json> {
    const r = await fetch(`${this.runtimeUrl}/v1/capacity/${encodeURIComponent(identityId)}`, {
      headers: this.headers(),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`getCapacity failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async createVoucher(body: Json): Promise<Json> {
    const r = await fetch(`${this.runtimeUrl}/v1/vouchers`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`createVoucher failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async verifyVoucher(voucherId: string, sellerIdentityId: string, expectedAmount?: number): Promise<Json> {
    const payload: Json = { seller_identity_id: sellerIdentityId };
    if (expectedAmount !== undefined) payload.expected_amount = expectedAmount;
    const r = await fetch(`${this.runtimeUrl}/v1/vouchers/${encodeURIComponent(voucherId)}/verify`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`verifyVoucher failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async acceptVoucher(voucherId: string, sellerIdentityId: string): Promise<Json> {
    const r = await fetch(`${this.runtimeUrl}/v1/vouchers/${encodeURIComponent(voucherId)}/accept`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({ seller_identity_id: sellerIdentityId }),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`acceptVoucher failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async createSettlement(body: Json): Promise<Json> {
    const r = await fetch(`${this.runtimeUrl}/v1/settlement/create`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`createSettlement failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async markSettlementPending(taskId: string): Promise<Json> {
    const r = await fetch(`${this.runtimeUrl}/v1/settlement/${encodeURIComponent(taskId)}/pending`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({}),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`markSettlementPending failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async acceptTask(params: {
    taskId: string;
    buyerIdentityId: string;
    sellerIdentityId: string;
    voucherId: string;
    escrowAmount: number;
    currency?: string;
  }): Promise<Json> {
    await this.createSettlement({
      task_id: params.taskId,
      client_agent_id: params.buyerIdentityId,
      escrow_amount: params.escrowAmount,
      currency: params.currency ?? "USD",
      voucher_id: params.voucherId,
    });
    await this.markSettlementPending(params.taskId);
    return this.lockSettlement(params.taskId, params.sellerIdentityId);
  }

  async lockSettlement(taskId: string, workerAgentId: string): Promise<Json> {
    const r = await fetch(`${this.runtimeUrl}/v1/settlement/${encodeURIComponent(taskId)}/lock`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({ worker_agent_id: workerAgentId }),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`lockSettlement failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async autoArbitrate(taskId: string): Promise<Json> {
    const r = await fetch(`${this.runtimeUrl}/v1/settlement/${encodeURIComponent(taskId)}/auto-arbitrate`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({}),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`autoArbitrate failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async submitExecutionReceipt(receipt: Json): Promise<Json> {
    const r = await fetch(`${this.runtimeUrl}/v1/receipts`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(receipt),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`submitExecutionReceipt failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json;
  }

  async timeoutConfirmStaleProgress(taskId: string, maxPendingHours = 72): Promise<Json[]> {
    const q = new URLSearchParams({ max_pending_hours: String(maxPendingHours) });
    const r = await fetch(
      `${this.runtimeUrl}/v1/progress/task/${encodeURIComponent(taskId)}/timeout-confirm?${q.toString()}`,
      {
        method: "POST",
        headers: this.headers(),
        signal: AbortSignal.timeout(this.timeoutMs),
      },
    );
    if (!r.ok) throw new Error(`timeoutConfirmStaleProgress failed: ${r.status} ${await r.text()}`);
    return (await r.json()) as Json[];
  }
}

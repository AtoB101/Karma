/**
 * @karma-network/sdk — P0–P1 HTTP surface for Karma public API (TypeScript).
 * Mirrors Python `sdk.KarmaClient` lock / capacity / voucher / settlement / receipts
 * and exposes P1 typed receipt extension builders (hash-in / JSON-out).
 */
/**
 * Build ``kind: api`` extension when the caller already has lowercase hex SHA-256 digests
 * (64 chars). Keeps the TS SDK free of crypto so it works in browsers without polyfills.
 */
export function apiExecutionExtensionFromHashes(params) {
    return {
        kind: "api",
        request_hash: params.requestHash,
        response_hash: params.responseHash,
        http_status_code: params.httpStatusCode,
        latency_ms: params.latencyMs,
        error_code: params.errorCode ?? undefined,
    };
}
export function mcpExecutionExtensionFromHashes(params) {
    return {
        kind: "mcp",
        mcp_server_id: params.mcpServerId,
        mcp_tool_name: params.mcpToolName,
        trace_hash: params.traceHash,
        result_hash: params.resultHash,
    };
}
export function agentExecutionExtensionFromHashes(params) {
    return {
        kind: "agent",
        model_used: params.modelUsed,
        tool_calls_hash: params.toolCallsHash,
        step_log_hash: params.stepLogHash,
        runtime_trace_hash: params.runtimeTraceHash,
    };
}
export class KarmaPublicSdk {
    runtimeUrl;
    apiKey;
    timeoutMs;
    constructor(opts) {
        this.runtimeUrl = opts.runtimeUrl.replace(/\/$/, "");
        this.apiKey = opts.apiKey ?? "";
        this.timeoutMs = opts.timeoutMs ?? 120_000;
    }
    headers() {
        const h = { "content-type": "application/json" };
        if (this.apiKey)
            h["X-Karma-Api-Key"] = this.apiKey;
        return h;
    }
    async lockUsdc(identityId, amount) {
        const r = await fetch(`${this.runtimeUrl}/v1/capacity/${encodeURIComponent(identityId)}/lock`, {
            method: "POST",
            headers: this.headers(),
            body: JSON.stringify({ amount }),
            signal: AbortSignal.timeout(this.timeoutMs),
        });
        if (!r.ok)
            throw new Error(`lockUsdc failed: ${r.status} ${await r.text()}`);
        return (await r.json());
    }
    async getCapacity(identityId) {
        const r = await fetch(`${this.runtimeUrl}/v1/capacity/${encodeURIComponent(identityId)}`, {
            headers: this.headers(),
            signal: AbortSignal.timeout(this.timeoutMs),
        });
        if (!r.ok)
            throw new Error(`getCapacity failed: ${r.status} ${await r.text()}`);
        return (await r.json());
    }
    async createVoucher(body) {
        const r = await fetch(`${this.runtimeUrl}/v1/vouchers`, {
            method: "POST",
            headers: this.headers(),
            body: JSON.stringify(body),
            signal: AbortSignal.timeout(this.timeoutMs),
        });
        if (!r.ok)
            throw new Error(`createVoucher failed: ${r.status} ${await r.text()}`);
        return (await r.json());
    }
    async verifyVoucher(voucherId, sellerIdentityId, expectedAmount) {
        const payload = { seller_identity_id: sellerIdentityId };
        if (expectedAmount !== undefined)
            payload.expected_amount = expectedAmount;
        const r = await fetch(`${this.runtimeUrl}/v1/vouchers/${encodeURIComponent(voucherId)}/verify`, {
            method: "POST",
            headers: this.headers(),
            body: JSON.stringify(payload),
            signal: AbortSignal.timeout(this.timeoutMs),
        });
        if (!r.ok)
            throw new Error(`verifyVoucher failed: ${r.status} ${await r.text()}`);
        return (await r.json());
    }
    async acceptVoucher(voucherId, sellerIdentityId) {
        const r = await fetch(`${this.runtimeUrl}/v1/vouchers/${encodeURIComponent(voucherId)}/accept`, {
            method: "POST",
            headers: this.headers(),
            body: JSON.stringify({ seller_identity_id: sellerIdentityId }),
            signal: AbortSignal.timeout(this.timeoutMs),
        });
        if (!r.ok)
            throw new Error(`acceptVoucher failed: ${r.status} ${await r.text()}`);
        return (await r.json());
    }
    async createSettlement(body) {
        const r = await fetch(`${this.runtimeUrl}/v1/settlement/create`, {
            method: "POST",
            headers: this.headers(),
            body: JSON.stringify(body),
            signal: AbortSignal.timeout(this.timeoutMs),
        });
        if (!r.ok)
            throw new Error(`createSettlement failed: ${r.status} ${await r.text()}`);
        return (await r.json());
    }
    async markSettlementPending(taskId) {
        const r = await fetch(`${this.runtimeUrl}/v1/settlement/${encodeURIComponent(taskId)}/pending`, {
            method: "POST",
            headers: this.headers(),
            body: JSON.stringify({}),
            signal: AbortSignal.timeout(this.timeoutMs),
        });
        if (!r.ok)
            throw new Error(`markSettlementPending failed: ${r.status} ${await r.text()}`);
        return (await r.json());
    }
    async acceptTask(params) {
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
    async lockSettlement(taskId, workerAgentId) {
        const r = await fetch(`${this.runtimeUrl}/v1/settlement/${encodeURIComponent(taskId)}/lock`, {
            method: "POST",
            headers: this.headers(),
            body: JSON.stringify({ worker_agent_id: workerAgentId }),
            signal: AbortSignal.timeout(this.timeoutMs),
        });
        if (!r.ok)
            throw new Error(`lockSettlement failed: ${r.status} ${await r.text()}`);
        return (await r.json());
    }
    async submitExecutionReceipt(receipt) {
        const r = await fetch(`${this.runtimeUrl}/v1/receipts`, {
            method: "POST",
            headers: this.headers(),
            body: JSON.stringify(receipt),
            signal: AbortSignal.timeout(this.timeoutMs),
        });
        if (!r.ok)
            throw new Error(`submitExecutionReceipt failed: ${r.status} ${await r.text()}`);
        return (await r.json());
    }
}

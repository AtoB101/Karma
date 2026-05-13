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
export type ExecutionReceiptExtension = ApiExecutionReceiptExtension | McpExecutionReceiptExtension | AgentExecutionReceiptExtension;
/**
 * Build ``kind: api`` extension when the caller already has lowercase hex SHA-256 digests
 * (64 chars). Keeps the TS SDK free of crypto so it works in browsers without polyfills.
 */
export declare function apiExecutionExtensionFromHashes(params: {
    requestHash: string;
    responseHash: string;
    httpStatusCode: number;
    latencyMs: number;
    errorCode?: string | null;
}): ApiExecutionReceiptExtension;
export declare function mcpExecutionExtensionFromHashes(params: {
    mcpServerId: string;
    mcpToolName: string;
    traceHash: string;
    resultHash: string;
}): McpExecutionReceiptExtension;
export declare function agentExecutionExtensionFromHashes(params: {
    modelUsed: string;
    toolCallsHash: string;
    stepLogHash: string;
    runtimeTraceHash: string;
}): AgentExecutionReceiptExtension;
export interface KarmaSdkOptions {
    runtimeUrl: string;
    apiKey?: string;
    timeoutMs?: number;
}
export declare class KarmaPublicSdk {
    readonly runtimeUrl: string;
    readonly apiKey: string;
    readonly timeoutMs: number;
    constructor(opts: KarmaSdkOptions);
    private headers;
    lockUsdc(identityId: string, amount: number): Promise<Json>;
    getCapacity(identityId: string): Promise<Json>;
    createVoucher(body: Json): Promise<Json>;
    verifyVoucher(voucherId: string, sellerIdentityId: string, expectedAmount?: number): Promise<Json>;
    acceptVoucher(voucherId: string, sellerIdentityId: string): Promise<Json>;
    createSettlement(body: Json): Promise<Json>;
    markSettlementPending(taskId: string): Promise<Json>;
    acceptTask(params: {
        taskId: string;
        buyerIdentityId: string;
        sellerIdentityId: string;
        voucherId: string;
        escrowAmount: number;
        currency?: string;
    }): Promise<Json>;
    lockSettlement(taskId: string, workerAgentId: string): Promise<Json>;
    autoArbitrate(taskId: string): Promise<Json>;
    submitExecutionReceipt(receipt: Json): Promise<Json>;
    timeoutConfirmStaleProgress(taskId: string, maxPendingHours?: number): Promise<Json[]>;
}

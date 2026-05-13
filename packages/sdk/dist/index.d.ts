/**
 * @karma-network/sdk — P0 HTTP surface for Karma public API (TypeScript).
 * Mirrors Python `sdk.KarmaClient` lock / capacity / voucher / settlement / receipts.
 */
export type Json = Record<string, unknown>;
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
    submitExecutionReceipt(receipt: Json): Promise<Json>;
}

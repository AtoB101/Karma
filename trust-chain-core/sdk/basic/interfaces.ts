export type TransactionContext = {
  txId: string;
  payer: string;
  payee: string;
  token: string;
  amount: string;
  timestamp: string;
};

export type RiskCheckResult = {
  allow: boolean;
  reason?: string;
  riskLevel?: "low" | "medium" | "high";
};

export interface RiskEngine {
  check(tx: TransactionContext): Promise<RiskCheckResult>;
}

export interface SettlementOptimizer {
  pickMode(tx: TransactionContext): Promise<"single" | "batch">;
}

export interface RoutingEngine {
  selectRoute(tx: TransactionContext): Promise<string>;
}

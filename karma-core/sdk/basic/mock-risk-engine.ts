import type {
  RiskCheckResult,
  RiskEngine,
  TransactionContext,
} from "./interfaces";

/**
 * Public mock implementation.
 * Real production logic is private and lives in the private engine repository (not in this public tree).
 */
export class MockRiskEngine implements RiskEngine {
  async check(_tx: TransactionContext): Promise<RiskCheckResult> {
    return {
      status: "review",
      score: 50,
      reasonCode: "MOCK_ENGINE_PUBLIC_ONLY",
    };
  }
}

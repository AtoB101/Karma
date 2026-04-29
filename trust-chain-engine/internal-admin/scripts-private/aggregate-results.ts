import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

type BatchResult = {
  timestamp: string;
  config: {
    engineAddress: string;
    tokenAddress: string;
    payeeAddress: string;
    batchSize: number;
    minAmount: string;
    maxAmount: string;
    delayMs: number;
    deadlineSeconds: number;
    chainId: number;
  };
  summary: {
    attempted: number;
    sent: number;
    succeeded: number;
    failed: number;
    successRate: number;
  };
  failureReasons: Record<string, number>;
  txHashes: string[];
};

function loadResults(resultsDir: string): BatchResult[] {
  const files = readdirSync(resultsDir)
    .filter((f) => f.endsWith(".json"))
    .sort();

  const rows: BatchResult[] = [];
  for (const file of files) {
    const raw = readFileSync(join(resultsDir, file), "utf-8");
    rows.push(JSON.parse(raw) as BatchResult);
  }
  return rows;
}

function main() {
  const resultsDir = process.env.RESULTS_DIR ?? "results";
  const outputPath = process.env.AGGREGATE_OUTPUT ?? "results/aggregate-summary.json";

  const rows = loadResults(resultsDir);
  if (rows.length === 0) {
    throw new Error(`No JSON result files found in ${resultsDir}`);
  }

  let totalAttempted = 0;
  let totalSent = 0;
  let totalSucceeded = 0;
  let totalFailed = 0;
  const failureReasons: Record<string, number> = {};

  for (const row of rows) {
    totalAttempted += row.summary.attempted;
    totalSent += row.summary.sent;
    totalSucceeded += row.summary.succeeded;
    totalFailed += row.summary.failed;
    for (const [k, v] of Object.entries(row.failureReasons ?? {})) {
      failureReasons[k] = (failureReasons[k] ?? 0) + v;
    }
  }

  const overallSuccessRate = totalAttempted === 0 ? 0 : Number(((totalSucceeded / totalAttempted) * 100).toFixed(2));

  const payload = {
    generatedAt: new Date().toISOString(),
    runs: rows.length,
    totals: {
      attempted: totalAttempted,
      sent: totalSent,
      succeeded: totalSucceeded,
      failed: totalFailed,
      overallSuccessRate,
    },
    failureReasons,
    perRun: rows.map((r) => ({
      timestamp: r.timestamp,
      batchSize: r.config.batchSize,
      attempted: r.summary.attempted,
      succeeded: r.summary.succeeded,
      failed: r.summary.failed,
      successRate: r.summary.successRate,
      chainId: r.config.chainId,
    })),
  };

  writeFileSync(outputPath, JSON.stringify(payload, null, 2), "utf-8");

  console.log("Aggregate summary written:", outputPath);
  console.log("Runs:", payload.runs);
  console.log("Overall success rate:", `${payload.totals.overallSuccessRate}%`);
  console.log("Failure reasons:", payload.failureReasons);
}

main();

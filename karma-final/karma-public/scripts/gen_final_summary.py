#!/usr/bin/env python3
"""Generate comprehensive all-phases MARKET_SCENARIO_SUMMARY.json"""
import json
from pathlib import Path

base = Path("results/market-scenario-test")
all_data = {"simulation_name": "karma_market_scenario_validation_all_phases", "phases": {}}

for phase in ["A", "B", "C"]:
    summary_path = base / f"phase_{phase}" / "MARKET_SCENARIO_SUMMARY.json"
    if summary_path.exists():
        with open(summary_path) as f:
            all_data["phases"][f"phase_{phase}"] = json.load(f)

# Use Phase C as the canonical summary
phase_c = all_data["phases"].get("phase_C", {})
all_data["final_recommendation"] = phase_c.get("recommendation", {})

# Aggregate metrics
all_data["aggregate"] = {
    "total_phases": 3,
    "total_tasks_all_markets": sum(
        sum(m.get("total_tasks", 0) for m in p.get("markets", {}).values())
        for p in all_data["phases"].values()
    ),
    "all_phases_pass": all(
        all(m.get("verdict") == "PASS" for m in p.get("markets", {}).values())
        for p in all_data["phases"].values()
    ),
}

with open(base / "MARKET_SCENARIO_SUMMARY.json", "w") as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False)
print("Generated MARKET_SCENARIO_SUMMARY.json")

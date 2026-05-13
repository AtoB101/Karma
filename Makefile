.PHONY: build test test-python test-gas deploy demo simulate verify proof clean karma-bff-smoke

# Python: 单元 + 集成（含 Runtime /runtime 端到端，见 tests/integration/test_runtime_e2e.py）
test-python:
	python3 -m pip install -q -e ".[dev]"
	python3 -m pytest tests/ -q --tb=short

karma-bff-smoke:
	pip install -q -r requirements-bff.txt httpx
	PYTHONPATH=. python3 -m unittest tests.test_karma_bff_smoke -v

build:
	forge build

test:
	forge test -vv

test-gas:
	forge test --gas-report

deploy:
	@echo "NOTE: Legacy LockPool/BillManager DeployDemo was removed when merging main (karma-core layout)."
	@echo "      Use: forge test (contracts under karma-core/) or docs/TESTNET_RUNBOOK.md for on-chain flows."
	@exit 1

demo:
	@echo "NOTE: Legacy run-demo.sh stack is incompatible with current karma-core contracts."
	@echo "      For Trusted Agent: python3 scripts/trusted_agent_minimal_flow.py"
	@echo "      For hybrid/testnet: see docs/TESTNET_RUNBOOK.md"
	@exit 1

simulate:
	node scripts/simulate.cjs

verify:
	node scripts/verify.cjs

proof:
	node scripts/proof.cjs

full: simulate verify proof

frontend:
	@echo "Starting frontend on http://localhost:8787"
	python3 -m http.server 8787

clean:
	rm -rf out cache deployment.json abis.json results/
	forge clean

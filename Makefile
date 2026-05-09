.PHONY: build test deploy demo simulate verify proof clean

build:
	forge build

test:
	forge test -vv

test-gas:
	forge test --gas-report

deploy:
	forge script contracts/script/DeployDemo.s.sol --rpc-url http://127.0.0.1:8545 --broadcast --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

demo:
	./run-demo.sh

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

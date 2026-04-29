.PHONY: help quickstart quickstart-skip-deploy preflight doctor doctor-json support-bundle ci-local ci-local-env proof-sop-checklist verify-proof-index verify-proof-index-batch validate-evidence-schema validate-output-contracts slither-gate ci-proof-gates ci-proof-gate proof-patrol agent-safety-guardian guardian rule-gap-adversarial-sim api-run api-smoke commercialization-gate release-readiness system-status ops-alert ops-summary ops-health ops-doctor-json ops-support ops-proof-gates ops-commercialization-gate safety-guardian safety-patrol safety-rulegap safety-commercial-gate api-health api-contract

SCRIPTS_DIR := ../scripts
REPO_ROOT := ../../..

help:
	@echo "Available targets:"
	@echo "  make quickstart            # preflight + deploy + start frontend (from .env)"
	@echo "  make quickstart-skip-deploy # preflight + start frontend only (from .env)"
	@echo "  make preflight             # run setup checks (from .env)"
	@echo "  make doctor                # generate local diagnosis report for support"
	@echo "  make doctor-json           # generate machine-readable diagnosis JSON"
	@echo "  make support-bundle        # zip diagnostics + key artifacts for support"
	@echo "  make ci-local              # run local CI checks (local preflight + build + core tests)"
	@echo "  make ci-local-env          # run local CI checks with .env loaded"
	@echo "  make proof-sop-checklist   # generate proof verification SOP record template"
	@echo "  make verify-proof-index    # verify manifest digest in latest support bundle"
	@echo "  make verify-proof-index-batch # batch verify manifests under results/"
	@echo "  make validate-evidence-schema # validate exported diagnosis JSON schema compatibility"
	@echo "  make validate-output-contracts # validate top-level output contract fields"
	@echo "  make slither-gate            # run Slither static analysis gate"
	@echo "  make ci-proof-gates          # run M4.1 proof/evidence CI gate checks"
	@echo "  make ci-proof-gate           # alias of ci-proof-gates"
	@echo "  make proof-patrol            # run M4.2 scheduled patrol profile (strict by default)"
	@echo "  make agent-safety-guardian   # run end-to-end safety guardian (self-check + risk registry)"
	@echo "  make guardian                # alias of agent-safety-guardian"
	@echo "  make rule-gap-adversarial-sim # run rule-exploit adversarial simulation scenarios"
	@echo "  make api-run                 # start TrustChain ecosystem API server on :8811"
	@echo "  make api-smoke               # run API smoke tests against local server"
	@echo "  make commercialization-gate  # evaluate commercial readiness (MUST/SHOULD/CAN)"
	@echo "  make release-readiness       # run full release gate chain (fail-fast)"
	@echo "  make system-status           # aggregate latest operational status to system-status JSON"
	@echo "  make ops-alert               # export alert-friendly JSON artifact for routing"
	@echo "  make ops-summary             # one-command operational summary and status digest"
	@echo "  make ops-health              # run doctor + preflight(local) baseline checks (needs forge/cast)"
	@echo "  make ops-doctor-json         # run doctor JSON report only (no forge/cast requirement)"
	@echo "  make ops-support             # generate support bundle + verify latest proof index"
	@echo "  make ops-proof-gates         # run proof/evidence gate checks (ops alias)"
	@echo "  make ops-commercialization-gate # run commercial readiness gate (ops alias)"
	@echo "  make safety-guardian         # run agent safety guardian (safety alias)"
	@echo "  make safety-patrol           # run strict safety patrol (safety alias)"
	@echo "  make safety-rulegap          # run adversarial rule-gap simulation (safety alias)"
	@echo "  make safety-commercial-gate  # run commercialization gate (safety alias)"
	@echo "  make api-health              # check API health endpoint"
	@echo "  make api-contract            # verify OpenAPI contract file exists"

quickstart:
	@$(SCRIPTS_DIR)/dev-up.sh --from-env

quickstart-skip-deploy:
	@$(SCRIPTS_DIR)/dev-up.sh --from-env --skip-deploy

preflight:
	@$(SCRIPTS_DIR)/preflight.sh --from-env

doctor:
	@$(SCRIPTS_DIR)/doctor.sh --port 8790

doctor-json:
	@$(SCRIPTS_DIR)/doctor.sh --port 8790 --format json --output results/doctor-report.json

support-bundle:
	@$(SCRIPTS_DIR)/support-bundle.sh --port 8790

ci-local:
	@$(SCRIPTS_DIR)/ci-local.sh

ci-local-env:
	@$(SCRIPTS_DIR)/ci-local.sh --from-env

proof-sop-checklist:
	@$(SCRIPTS_DIR)/proof-sop-checklist.sh

verify-proof-index:
	@LATEST_ZIP=$$(ls -t results/support-bundle-*.zip 2>/dev/null | head -n 1); \
	if [[ -z "$$LATEST_ZIP" ]]; then \
	  echo "No support-bundle zip found in results/. Run: make support-bundle"; \
	  exit 1; \
	fi; \
	$(SCRIPTS_DIR)/verify-proof-index.sh --path "$$LATEST_ZIP"

verify-proof-index-batch:
	@$(SCRIPTS_DIR)/verify-proof-index-batch.sh --dir results --glob "support-bundle-*.zip"

validate-evidence-schema:
	@LATEST_JSON=$$(ls -t results/trustchain-v01-diagnosis-*.json 2>/dev/null | head -n 1); \
	if [[ -z "$$LATEST_JSON" ]]; then \
	  echo "No diagnosis JSON found in results/. Export one from frontend first."; \
	  exit 1; \
	fi; \
	$(SCRIPTS_DIR)/validate-evidence-schema.sh --path "$$LATEST_JSON"

validate-output-contracts:
	@$(SCRIPTS_DIR)/validate-output-contracts.sh --format text

slither-gate:
	@$(SCRIPTS_DIR)/slither-gate.sh --format text --output results/slither-gate-latest.txt

ci-proof-gates:
	@$(SCRIPTS_DIR)/ci-proof-gates.sh

ci-proof-gate: ci-proof-gates
	@:

proof-patrol:
	@$(SCRIPTS_DIR)/proof-patrol.sh --profile strict --batch-output results/proof-patrol-batch-latest.json --alert-output results/proof-patrol-alert-latest.json

agent-safety-guardian:
	@$(SCRIPTS_DIR)/agent-safety-guardian.sh --profile balanced

guardian: agent-safety-guardian
	@:

rule-gap-adversarial-sim:
	@$(SCRIPTS_DIR)/rule-gap-adversarial-sim.sh

api-run:
	@$(SCRIPTS_DIR)/api_server.py --host 127.0.0.1 --port 8811 --results-dir results

api-smoke:
	@$(SCRIPTS_DIR)/api-smoke.sh --host 127.0.0.1 --port 8811

commercialization-gate:
	@$(SCRIPTS_DIR)/commercialization-gate.sh --output results/commercialization-gate-latest.json --format text

release-readiness:
	@$(SCRIPTS_DIR)/release-readiness.sh

system-status:
	@$(SCRIPTS_DIR)/system-status.sh --output results/system-status-latest.json --format text

ops-alert:
	@$(SCRIPTS_DIR)/ops-alert.sh --input results/system-status-latest.json --output results/ops-alert-latest.json --format text

ops-summary:
	@$(SCRIPTS_DIR)/ops-summary.sh

ops-health:
	@$(SCRIPTS_DIR)/doctor.sh --port 8790 --format text --output results/doctor-report.txt
	@$(SCRIPTS_DIR)/preflight.sh --mode local

ops-doctor-json:
	@$(SCRIPTS_DIR)/doctor.sh --port 8790 --format json --output results/doctor-report.json

ops-support: support-bundle verify-proof-index
	@:

ops-proof-gates: ci-proof-gates
	@:

ops-commercialization-gate: commercialization-gate
	@:

safety-guardian: agent-safety-guardian
	@:

safety-patrol:
	@$(SCRIPTS_DIR)/proof-patrol.sh --profile strict --batch-output results/proof-patrol-batch-latest.json --alert-output results/proof-patrol-alert-latest.json

safety-rulegap: rule-gap-adversarial-sim
	@:

safety-commercial-gate: commercialization-gate
	@:

api-health:
	@curl -fsS "http://127.0.0.1:8811/api/v1/health" >/dev/null && echo "API health: ok"

api-contract:
	@test -f "$(REPO_ROOT)/openapi/karma-v1.yaml" && echo "OpenAPI contract: $(REPO_ROOT)/openapi/karma-v1.yaml"

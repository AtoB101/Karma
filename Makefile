.PHONY: help quickstart quickstart-skip-deploy preflight doctor doctor-json support-bundle ci-local ci-local-env proof-sop-checklist verify-proof-index verify-proof-index-batch

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

quickstart:
	@./scripts/dev-up.sh --from-env

quickstart-skip-deploy:
	@./scripts/dev-up.sh --from-env --skip-deploy

preflight:
	@./scripts/preflight.sh --from-env

doctor:
	@./scripts/doctor.sh --port 8790

doctor-json:
	@./scripts/doctor.sh --port 8790 --format json --output results/doctor-report.json

support-bundle:
	@./scripts/support-bundle.sh --port 8790

ci-local:
	@./scripts/ci-local.sh

ci-local-env:
	@./scripts/ci-local.sh --from-env

proof-sop-checklist:
	@./scripts/proof-sop-checklist.sh

verify-proof-index:
	@LATEST_ZIP=$$(ls -t results/support-bundle-*.zip 2>/dev/null | head -n 1); \
	if [[ -z "$$LATEST_ZIP" ]]; then \
	  echo "No support-bundle zip found in results/. Run: make support-bundle"; \
	  exit 1; \
	fi; \
	./scripts/verify-proof-index.sh --path "$$LATEST_ZIP"

verify-proof-index-batch:
	@./scripts/verify-proof-index-batch.sh --dir results --glob "support-bundle-*.zip"

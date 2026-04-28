.PHONY: help quickstart quickstart-skip-deploy preflight doctor doctor-json support-bundle

help:
	@echo "Available targets:"
	@echo "  make quickstart            # preflight + deploy + start frontend (from .env)"
	@echo "  make quickstart-skip-deploy # preflight + start frontend only (from .env)"
	@echo "  make preflight             # run setup checks (from .env)"
	@echo "  make doctor                # generate local diagnosis report for support"
	@echo "  make doctor-json           # generate machine-readable diagnosis JSON"
	@echo "  make support-bundle        # zip diagnostics + key artifacts for support"

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

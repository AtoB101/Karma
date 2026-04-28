.PHONY: help quickstart quickstart-skip-deploy preflight doctor doctor-json

help:
	@echo "Available targets:"
	@echo "  make quickstart            # preflight + deploy + start frontend (from .env)"
	@echo "  make quickstart-skip-deploy # preflight + start frontend only (from .env)"
	@echo "  make preflight             # run setup checks (from .env)"
	@echo "  make doctor                # generate local diagnosis report for support"
	@echo "  make doctor-json           # generate machine-readable diagnosis JSON"

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

.PHONY: help quickstart quickstart-skip-deploy preflight

help:
	@echo "Available targets:"
	@echo "  make quickstart            # preflight + deploy + start frontend (from .env)"
	@echo "  make quickstart-skip-deploy # preflight + start frontend only (from .env)"
	@echo "  make preflight             # run setup checks (from .env)"

quickstart:
	@./scripts/dev-up.sh --from-env

quickstart-skip-deploy:
	@./scripts/dev-up.sh --from-env --skip-deploy

preflight:
	@./scripts/preflight.sh --from-env

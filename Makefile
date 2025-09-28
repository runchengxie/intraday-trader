.PHONY: help backtest update live dashboard lint docker-build docker-backtest docker-live docker-db

UV ?= uv

help:
	@echo "Common workflows:" \
	&& echo "  make backtest       # Run local backtest via patf CLI" \
	&& echo "  make update         # Refresh cached market data" \
	&& echo "  make live           # Start local live trading session" \
	&& echo "  make dashboard      # Launch Streamlit dashboard" \
	&& echo "  make lint           # Run Ruff lint + format checks" \
	&& echo "Docker helpers (use --profile live/db as needed):" \
	&& echo "  make docker-build   # Build trading image" \
	&& echo "  make docker-backtest # Run backtest inside container" \
	&& echo "  make docker-live    # Bring up live stack (db + bot)" \
	&& echo "  make docker-db      # Start TimescaleDB only"

backtest:
	patf run-backtest

update:
	patf run-update-data

live:
	patf run-live

dashboard:
	patf run-dashboard

lint:
	$(UV) run ruff check .

docker-build:
	docker compose build

docker-backtest:
	docker compose --profile live run --rm trading-bot patf run-backtest

docker-live:
	docker compose --profile live up trading-bot

docker-db:
	docker compose --profile db up db

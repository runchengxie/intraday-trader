.PHONY: help sync backtest optimise benchmark update live dashboard lint fmt coverage typecheck ci docker-build docker-backtest docker-live docker-db

UV ?= uv
UV_FLAGS ?=

ifeq ($(USE_ACTIVE),1)
  UV_FLAGS += --active
  CLEAR_ENV =
else
  CLEAR_ENV = env -u VIRTUAL_ENV
endif

define UV_RUN
	$(CLEAR_ENV) $(UV) run $(UV_FLAGS) $(1)
endef

help:
	@echo "Common workflows:" \
	&& echo "  make sync           # Install project dependencies" \
	&& echo "  make backtest       # Run local backtest via intraday CLI" \
	&& echo "  make optimise       # Optimise strategy parameters" \
	&& echo "  make benchmark      # Produce buy-and-hold benchmark only" \
	&& echo "  make update         # Refresh cached market data" \
	&& echo "  make live           # Start local live trading session" \
	&& echo "  make dashboard      # Launch Streamlit dashboard" \
	&& echo "  make lint           # Run Ruff lint checks" \
	&& echo "  make fmt            # Run Ruff formatter" \
	&& echo "  make typecheck      # Run Pyright type checker" \
	&& echo "  make coverage       # Run pytest coverage" \
	&& echo "  make ci             # Full CI: lint + fmt + typecheck + test" \
	&& echo "Docker helpers (use --profile live/db as needed):" \
	&& echo "  make docker-build   # Build trading image" \
	&& echo "  make docker-backtest # Run backtest inside container" \
	&& echo "  make docker-live    # Bring up live stack (db + bot)" \
	&& echo "  make docker-db      # Start TimescaleDB only"

sync:
	$(CLEAR_ENV) $(UV) sync $(UV_FLAGS)

backtest:
	$(call UV_RUN,intraday backtest run $(ARGS))

optimise:
	$(call UV_RUN,intraday backtest optimise $(ARGS))

benchmark:
	$(call UV_RUN,intraday backtest benchmark $(ARGS))

update:
	$(call UV_RUN,intraday update-data $(ARGS))

live:
	$(call UV_RUN,intraday live $(ARGS))

dashboard:
	$(call UV_RUN,intraday dashboard $(ARGS))

lint:
	$(call UV_RUN,ruff check .)

fmt:
	$(call UV_RUN,ruff format .)

coverage:
	$(call UV_RUN,pytest --cov=intraday_trader --cov-report=term-missing)

typecheck:
	$(call UV_RUN,pyright src tests)

ci: lint fmt typecheck coverage

docker-build:
	docker compose build

docker-backtest:
	docker compose --profile live run --rm trading-bot intraday backtest run $(ARGS)

docker-live:
	docker compose --profile live up trading-bot

docker-db:
	docker compose --profile db up db

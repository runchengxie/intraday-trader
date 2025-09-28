# Repository Guidelines

## Project Structure & Module Organization
The production package lives in `src/intraday_trader_air/`, with `backtest/`, `strategies/`, and helper modules (`data_utils.py`, `risk_manager.py`, `dashboard_app.py`) forming the trading pipeline. CLI entrypoints reside in `src/intraday_trader_air/scripts/` and surface through the `intraday` command declared in `pyproject.toml`. Tests mirror the package under `tests/unit`, `tests/integration`, and `tests/e2e`; share fixtures in `tests/conftest.py`. Root-level automation files (`Makefile`, `docker-compose.yml`, `Dockerfile`) and `config.yml` drive orchestration, while reference material belongs in `docs/`.

## Build, Test, and Development Commands
- `uv sync && uv pip install -e .` sets up an editable environment with the dev toolchain.
- `intraday backtest run`, `intraday update-data`, and `intraday live` exercise the core workflows; pair flags like `--config config.yml` when experimenting.
- `make backtest`, `make lint`, `make fmt`, `make coverage`, and `make docker-live` wrap common tasks; compose profiles ensure TimescaleDB starts before the live bot.

## Coding Style & Naming Conventions
Follow Python 3.10 syntax, four-space indentation, and Ruff’s 88-character line limit. Modules and functions stay `snake_case`, classes use `PascalCase`, and constants remain uppercase. Run `uv run ruff check .` and `uv run ruff format .` before every push; justify any lint suppression in code review notes.

## Testing Guidelines
Pytest powers the suite. Use `uv run pytest` for fast smoke coverage and `make coverage` when preparing reports (`--cov=intraday_trader_air`). Apply the existing markers: `pytest -m integration` isolates external service calls, whereas `pytest -m "not integration"` keeps CI focused on unit tests. Name new files after their targets (e.g., `tests/unit/test_risk_manager.py`) and reuse fixtures rather than mocking brokers repeatedly.

## Commit & Pull Request Guidelines
Commits follow a short, present-tense style (`Rename framework to intraday-trader-air`); add a scope prefix when helpful (`strategies: add ema crossover`). Ensure each commit passes lint and unit tests locally. Pull requests should link issues, call out trading-impacting changes, and attach screenshots or CLI excerpts for dashboard or terminal output.

## Environment & Configuration Tips
Copy `.env.example` to `.env` for Alpaca keys and database credentials, then keep the file out of version control. Switch storage backends through `config.yml` (`sqlite`, `parquet`, `postgresql`) and document schema migrations when altering tables. For Docker flows, prefer `docker compose --profile live up trading-bot` so the health checks gate the trading service on TimescaleDB readiness.

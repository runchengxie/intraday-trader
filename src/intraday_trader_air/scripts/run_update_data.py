import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from alpaca_trade_api.rest import REST, TimeFrame
from dotenv import load_dotenv

from intraday_trader_air.configuration import load_app_config
from intraday_trader_air.data_quality import (
    build_expected_frequency,
    run_quality_checks,
    write_quality_report,
)
from intraday_trader_air.data_utils import fetch_historical_data
from intraday_trader_air.db_handler import DBHandler

# (Configure logging)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)


def main():
    """Fetches the latest market data and saves it to the database."""
    # --- Path Resolution ---
    # The Docker container's working directory is /app. We can therefore
    # use a simple relative path, which works both locally and in Docker.
    config_path = Path("config.yml")
    dotenv_path = Path(".env")

    # Load environment variables from .env file *before* loading config
    load_dotenv(dotenv_path=dotenv_path)
    logging.info(f"Loaded environment variables from: {dotenv_path}")

    config = load_app_config(config_path)

    db_handler = DBHandler(asdict(config.database) if config.database else {})
    db_handler.initialize_db()

    API_KEY = os.getenv("APCA_API_KEY_ID")
    SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
    BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not API_KEY or not SECRET_KEY:
        raise RuntimeError(
            "APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env"
        )

    api = REST(API_KEY, SECRET_KEY, base_url=BASE_URL)  # type: ignore[arg-type]

    # --- Core Logic ---
    # Usually fetch data for yesterday
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    symbol = config.data.ticker  # Or receive from command line arguments

    logging.info(f"Fetching data for {symbol} for date: {yesterday}")

    # fetch_historical_data already includes logic to write to the database
    bars = fetch_historical_data(
        api=api,
        symbol=symbol,
        timeframe=TimeFrame.Minute,  # type: ignore  # Fetch minute data
        start_date=yesterday,
        end_date=yesterday,
        cache_dir=str(config.paths.cache_dir),
        db_handler=db_handler,
        adjustment=config.data.adjustment,
    )

    if bars is None or bars.empty:
        logging.warning("No bars returned; skipping data quality checks")
        return

    expected_freq = build_expected_frequency(
        config.data.timeframe_value, config.data.timeframe_unit
    )
    report = run_quality_checks(bars, expected_freq, symbol)
    report_path = write_quality_report(report, config.paths.output_dir)
    if report.get("warnings"):
        logging.warning(
            "Data quality warnings detected for %s. See %s for details.",
            symbol,
            report_path,
        )
    else:
        logging.info("Data quality checks passed for %s", symbol)

    logging.info("Market data update task finished.")


if __name__ == "__main__":
    main()

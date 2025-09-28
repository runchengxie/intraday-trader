import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from alpaca_trade_api.rest import REST, TimeFrame
from dotenv import load_dotenv

from patf_trading_framework.data_utils import fetch_historical_data
from patf_trading_framework.db_handler import DBHandler

from .run_backtests import load_config

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

    config = load_config(config_path)

    db_handler = DBHandler(config["database"])
    db_handler.initialize_db()

    API_KEY = os.getenv("APCA_API_KEY_ID")
    SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
    BASE_URL = os.getenv("ALPACA_BASE_URL")
    api = REST(API_KEY, SECRET_KEY, base_url=BASE_URL)

    # --- Core Logic ---
    # Usually fetch data for yesterday
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    symbol = config["data"]["ticker"]  # Or receive from command line arguments

    logging.info(f"Fetching data for {symbol} for date: {yesterday}")

    # fetch_historical_data already includes logic to write to the database
    fetch_historical_data(
        api=api,
        symbol=symbol,
        timeframe=TimeFrame.Minute,  # Fetch minute data
        start_date=yesterday,
        end_date=yesterday,
        cache_dir=config["paths"]["cache_dir"],
        db_handler=db_handler,
    )

    logging.info("Market data update task finished.")


if __name__ == "__main__":
    main()

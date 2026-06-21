import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from intraday_trader_air.configuration import load_app_config
from intraday_trader_air.db_handler import DBHandler
from intraday_trader_air.logging_utils import ensure_directory
from intraday_trader_air.performance_analyzer import PerformanceAnalyzer


def main():
    """Generates a performance report based on data from the database."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # --- Path Resolution ---
    # The Docker container's working directory is /app. We can therefore
    # use a simple relative path, which works both locally and in Docker.
    config_path = "config.yml"
    dotenv_path = ".env"

    # Load environment variables from .env file first
    load_dotenv(dotenv_path=dotenv_path)

    config = load_app_config(Path(config_path))

    db_handler = DBHandler(asdict(config.database) if config.database else {})

    # Fetch trade logs and performance snapshots from the last day
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)

    trade_logs = db_handler.get_trade_logs(start_date, end_date)
    performance_snapshots = db_handler.get_performance_snapshots(start_date, end_date)

    analyzer = PerformanceAnalyzer(initial_capital=config.backtest.initial_cash)

    # Populate analyzer with data fetched from the database
    for trade in trade_logs:
        analyzer.record_trade(trade)

    for snapshot in performance_snapshots:
        analyzer.add_snapshot(snapshot.timestamp, snapshot.portfolio_value)

    report = analyzer.generate_performance_report()

    # Ensure the output directory exists
    output_dir = config.paths.output_dir
    ensure_directory(output_dir)

    # Save the report to a file
    report_filename = f"daily_report_{datetime.now().strftime('%Y%m%d')}.json"
    report_path = output_dir / report_filename
    with report_path.open("w", encoding="utf-8") as f:
        f.write(report)

    logging.info(f"Daily report generated at: {report_path}")


if __name__ == "__main__":
    main()

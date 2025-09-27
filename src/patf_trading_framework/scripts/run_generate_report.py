import logging
import os
import re
import sys
from datetime import datetime, timedelta
import yaml
from dotenv import load_dotenv

from patf_trading_framework.db_handler import DBHandler
from patf_trading_framework.performance_analyzer import PerformanceAnalyzer


def _sub_env(s: str) -> str:
    """
    Replace ${VAR} and ${VAR:-default} with env values.
    """

    def repl(m):
        expr = m.group(1)
        if ":-" in expr:
            var, default = expr.split(":-", 1)
            return os.getenv(var, default)
        return os.getenv(expr, m.group(0))

    return re.sub(r"\$\{([^}]+)\}", repl, s)


def load_config(config_path):
    """Load configuration from YAML file with environment variable substitution."""
    try:
        with open(config_path, encoding="utf-8") as f:
            raw_content = f.read()
        # Substitute environment variables before parsing
        substituted_content = _sub_env(raw_content)
        config = yaml.safe_load(substituted_content)
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file not found at: {config_path}")
        sys.exit(1)
    except yaml.YAMLError as e:
        logging.error(f"Error parsing configuration file '{config_path}': {e}")
        sys.exit(1)


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

    config = load_config(config_path)

    db_handler = DBHandler(config["database"])

    # Fetch trade logs and performance snapshots from the last day
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)

    trade_logs = db_handler.get_trade_logs(start_date, end_date)
    performance_snapshots = db_handler.get_performance_snapshots(start_date, end_date)

    analyzer = PerformanceAnalyzer(initial_capital=config["backtest"]["initial_cash"])

    # Populate analyzer with data fetched from the database
    for trade in trade_logs:
        analyzer.record_trade(trade)

    for snapshot in performance_snapshots:
        analyzer.add_snapshot(snapshot.timestamp, snapshot.portfolio_value)

    report = analyzer.generate_performance_report()

    # Ensure the output directory exists
    output_dir = config["paths"]["output_dir"]
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Save the report to a file
    report_filename = f"daily_report_{datetime.now().strftime('%Y%m%d')}.json"
    report_path = os.path.join(output_dir, report_filename)
    with open(report_path, "w") as f:
        f.write(report)

    logging.info(f"Daily report generated at: {report_path}")


if __name__ == "__main__":
    main()

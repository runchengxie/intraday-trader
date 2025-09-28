from pathlib import Path

import pytest

pytest.importorskip("yaml")

from intraday_trader_air.configuration import ConfigurationError, load_app_config


def test_load_app_config(tmp_path: Path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
        data:
          ticker: "SPY"
          timeframe_value: 15
          timeframe_unit: "Minute"
          start_date: "2024-01-01"
          end_date: "2024-01-31"
          adjustment: "split"
        paths:
          output_dir: "output"
          log_dir: "output/logs"
          chart_dir: "output/charts"
          cache_dir: "output/cache"
        benchmark:
          enabled: true
          total_return: true
        backtest:
          initial_cash: 100000
          commission: 0.001
          max_cpus: "auto"
        strategies:
          dummy:
            class_name: "MeanReversionZScoreStrategy"
        logging:
          level: "INFO"
          format: "%(message)s"
          datefmt: "%Y"
        """,
        encoding="utf-8",
    )

    config = load_app_config(config_path)
    assert config.data.resample_frequency == "15min"
    assert config.backtest.max_cpus >= 1
    assert config.benchmark.total_return is True
    assert config.strategies[0].key == "dummy"


def test_invalid_timeframe_raises(tmp_path: Path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
        data:
          ticker: "SPY"
          timeframe_value: 15
          timeframe_unit: "Invalid"
          start_date: "2024-01-01"
          end_date: "2024-01-31"
        paths:
          output_dir: "output"
          log_dir: "output/logs"
          chart_dir: "output/charts"
          cache_dir: "output/cache"
        benchmark:
          enabled: false
        backtest:
          initial_cash: 100000
          commission: 0.001
          max_cpus: 1
        strategies: {}
        logging:
          level: "INFO"
          format: "%(message)s"
          datefmt: "%Y"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        load_app_config(config_path)

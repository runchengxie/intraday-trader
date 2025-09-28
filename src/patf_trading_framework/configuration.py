"""Configuration loading and validation utilities for PATF."""

from __future__ import annotations

import multiprocessing
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

_ALLOWED_DB_BACKENDS = {"sqlite", "postgresql", "parquet"}
_ALLOWED_TIMEFRAME_UNITS = {"minute", "hour", "day"}
_ALLOWED_DATA_ADJUSTMENTS = {"raw", "split", "dividend", "all"}


class ConfigurationError(RuntimeError):
    """Raised when the user configuration cannot be parsed or validated."""


@dataclass(slots=True)
class PathsConfig:
    """Filesystem locations used by the framework."""

    output_dir: Path
    log_dir: Path
    chart_dir: Path
    cache_dir: Path


@dataclass(slots=True)
class LoggingConfig:
    """Logging configuration taken from the YAML file."""

    level: str
    fmt: str
    datefmt: str


@dataclass(slots=True)
class BenchmarkConfig:
    """Configuration for benchmark runs."""

    enabled: bool = False
    type: str = "buy_and_hold"
    size_pct: float = 1.0
    name: str = "Benchmark"
    total_return: bool = False


@dataclass(slots=True)
class BacktestConfig:
    """Backtest configuration details."""

    initial_cash: float
    commission: float
    slippage_perc: float = 0.0
    max_cpus: int = 1


@dataclass(slots=True)
class DataConfig:
    """Data configuration for historical fetches."""

    ticker: str
    timeframe_value: int
    timeframe_unit: str
    start_date: str
    end_date: str
    adjustment: str = "raw"

    @property
    def timeframe(self) -> str:
        return f"{self.timeframe_value} {self.timeframe_unit}"

    @property
    def resample_frequency(self) -> str:
        unit = self.timeframe_unit.lower()
        if unit.startswith("min"):
            suffix = "min"
        elif unit.startswith("hour"):
            suffix = "H"
        elif unit.startswith("day"):
            suffix = "D"
        else:  # pragma: no cover - validation prevents this
            suffix = unit
        return f"{self.timeframe_value}{suffix}"


@dataclass(slots=True)
class StrategyConfig:
    """Normalized representation of an individual strategy configuration."""

    key: str
    name: str
    class_name: str
    params: dict[str, Any] = field(default_factory=dict)
    opt_ranges: dict[str, Any] | None = None
    order_settings: dict[str, Any] | None = None
    use_filtered_data: bool = False


@dataclass(slots=True)
class DatabaseConfig:
    """Database connection information."""

    backend: str
    path: str | None = None
    host: str | None = None
    port: str | None = None
    user: str | None = None
    password: str | None = None
    dbname: str | None = None


@dataclass(slots=True)
class AppConfig:
    """Top-level configuration container."""

    data: DataConfig
    paths: PathsConfig
    benchmark: BenchmarkConfig
    backtest: BacktestConfig
    logging: LoggingConfig
    strategies: list[StrategyConfig]
    database: DatabaseConfig | None = None
    live_trading: Mapping[str, Any] | None = None


_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        expr = match.group(1)
        if ":-" in expr:
            var, default = expr.split(":-", 1)
            return os.getenv(var, default)
        return os.getenv(expr, match.group(0))

    return _ENV_VAR_PATTERN.sub(replace, text)


def _coerce_max_cpus(value: Any) -> int:
    if value is None:
        return 1
    if isinstance(value, str):
        value = value.strip().lower()
        if value == "auto":
            return max(1, multiprocessing.cpu_count() - 1 or 1)
        if value.isdigit():
            return max(1, int(value))
        raise ConfigurationError(f"Invalid max_cpus value: {value}")
    if isinstance(value, (int, float)):
        return max(1, int(value))
    raise ConfigurationError(f"Unsupported max_cpus type: {type(value)!r}")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ConfigurationError("PyYAML is required to load configuration files") from exc

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - fatal path
        raise ConfigurationError(f"Configuration file not found: {path}") from exc
    substituted = _substitute_env(raw)
    try:
        data = yaml.safe_load(substituted)
    except yaml.YAMLError as exc:  # pragma: no cover - fatal parsing
        raise ConfigurationError(f"Failed to parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError("Top-level configuration must be a mapping")
    return data


def _validate_data_config(data: Mapping[str, Any]) -> DataConfig:
    unit = data.get("timeframe_unit", "").lower()
    if unit not in _ALLOWED_TIMEFRAME_UNITS:
        raise ConfigurationError(
            "timeframe_unit must be one of minute/hour/day (case insensitive)"
        )
    adjustment = data.get("adjustment", "raw").lower()
    if adjustment not in _ALLOWED_DATA_ADJUSTMENTS:
        raise ConfigurationError(
            "data.adjustment must be one of raw/split/dividend/all"
        )
    return DataConfig(
        ticker=data["ticker"],
        timeframe_value=int(data["timeframe_value"]),
        timeframe_unit=data["timeframe_unit"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        adjustment=adjustment,
    )


def _validate_paths_config(paths: Mapping[str, Any]) -> PathsConfig:
    return PathsConfig(
        output_dir=Path(paths["output_dir"]).expanduser(),
        log_dir=Path(paths["log_dir"]).expanduser(),
        chart_dir=Path(paths["chart_dir"]).expanduser(),
        cache_dir=Path(paths["cache_dir"]).expanduser(),
    )


def _validate_logging_config(config: Mapping[str, Any]) -> LoggingConfig:
    return LoggingConfig(
        level=str(config.get("level", "INFO")).upper(),
        fmt=config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        datefmt=config.get("datefmt", "%Y-%m-%d %H:%M:%S"),
    )


def _validate_benchmark_config(config: Mapping[str, Any]) -> BenchmarkConfig:
    return BenchmarkConfig(
        enabled=bool(config.get("enabled", False)),
        type=config.get("type", "buy_and_hold"),
        size_pct=float(config.get("size_pct", 1.0)),
        name=config.get("name", "Benchmark"),
        total_return=bool(config.get("total_return", False)),
    )


def _validate_backtest_config(config: Mapping[str, Any]) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=float(config["initial_cash"]),
        commission=float(config.get("commission", 0.0)),
        slippage_perc=float(config.get("slippage_perc", 0.0)),
        max_cpus=_coerce_max_cpus(config.get("max_cpus")),
    )


def _validate_strategies_config(strategies: Mapping[str, Any]) -> list[StrategyConfig]:
    result: list[StrategyConfig] = []
    for key, raw in strategies.items():
        result.append(
            StrategyConfig(
                key=key,
                name=raw.get("name", key),
                class_name=raw["class_name"],
                params=dict(raw.get("params", {})),
                opt_ranges=dict(raw.get("opt_ranges", {})) or None,
                order_settings=dict(raw.get("order_settings", {})) or None,
                use_filtered_data=bool(raw.get("use_filtered_data", False)),
            )
        )
    return result


def _validate_database_config(data: Mapping[str, Any] | None) -> DatabaseConfig | None:
    if not data:
        return None
    backend = data.get("backend", "sqlite")
    if backend not in _ALLOWED_DB_BACKENDS:
        raise ConfigurationError(
            f"database.backend must be one of {_ALLOWED_DB_BACKENDS}, got {backend!r}"
        )
    return DatabaseConfig(
        backend=backend,
        path=data.get("path"),
        host=data.get("host"),
        port=data.get("port"),
        user=data.get("user"),
        password=data.get("password"),
        dbname=data.get("dbname"),
    )


def load_app_config(path: Path) -> AppConfig:
    """Load and validate the PATF configuration from ``path``."""

    data = _load_yaml(path)

    try:
        data_config = _validate_data_config(data["data"])
        paths_config = _validate_paths_config(data["paths"])
        benchmark_config = _validate_benchmark_config(data.get("benchmark", {}))
        backtest_config = _validate_backtest_config(data["backtest"])
        logging_config = _validate_logging_config(data.get("logging", {}))
        strategies_config = _validate_strategies_config(data.get("strategies", {}))
        database_config = _validate_database_config(data.get("database"))
    except KeyError as exc:
        raise ConfigurationError(f"Missing required configuration section: {exc.args[0]}")

    live_trading = data.get("live_trading")

    return AppConfig(
        data=data_config,
        paths=paths_config,
        benchmark=benchmark_config,
        backtest=backtest_config,
        logging=logging_config,
        strategies=strategies_config,
        database=database_config,
        live_trading=live_trading,
    )


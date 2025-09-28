"""Common pytest fixtures for PATF."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from patf_trading_framework.configuration import AppConfig, load_app_config


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def fake_config(project_root: Path, tmp_output_dir: Path) -> AppConfig:
    config_path = project_root / "config.yml"
    config = load_app_config(config_path)
    # Point outputs to the temporary directory to avoid polluting real artefacts
    config.paths = type(config.paths)(
        output_dir=tmp_output_dir,
        log_dir=tmp_output_dir / "logs",
        chart_dir=tmp_output_dir / "charts",
        cache_dir=tmp_output_dir / "cache",
    )
    for path in (config.paths.log_dir, config.paths.chart_dir, config.paths.cache_dir):
        path.mkdir(parents=True, exist_ok=True)
    return config


@pytest.fixture
def alpaca_stub() -> Iterator[object]:
    class _Stub:
        def __init__(self) -> None:
            self._calls: list[tuple[str, tuple, dict]] = []

        def get_bars(self, symbol, timeframe, start, end, adjustment="raw"):
            self._calls.append(("get_bars", (symbol, timeframe, start, end), {"adjustment": adjustment}))
            import pandas as pd

            index = pd.date_range(start=start, periods=2, freq="min", tz="UTC")
            frame = pd.DataFrame(
                {
                    "open": [100.0, 101.0],
                    "high": [101.0, 102.0],
                    "low": [99.0, 100.0],
                    "close": [100.5, 101.5],
                    "volume": [1000, 1100],
                },
                index=index,
            )
            frame.index.name = "timestamp"
            return type("Response", (), {"df": frame})

        def get_dividends(self, symbol, start, end):  # pragma: no cover - used selectively
            self._calls.append(("get_dividends", (symbol, start, end), {}))
            return type(
                "Dividends",
                (),
                {
                    "df": None,
                },
            )

    yield _Stub()


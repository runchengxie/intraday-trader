"""Common pytest fixtures for Intraday Trader Air."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from intraday_trader_air.configuration import AppConfig, load_app_config


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
            self._calls.append(
                (
                    "get_bars",
                    (symbol, timeframe, start, end),
                    {"adjustment": adjustment},
                )
            )
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

        def get_dividends(
            self, symbol, start, end
        ):  # pragma: no cover - used selectively
            self._calls.append(("get_dividends", (symbol, start, end), {}))
            return type(
                "Dividends",
                (),
                {
                    "df": None,
                },
            )

    yield _Stub()


@pytest.fixture
def mocker():
    """Lightweight substitute for ``pytest-mock``'s fixture."""

    active_patchers: list[object] = []

    class _PatchProxy:
        def __init__(self, outer: _Mocker) -> None:
            self._outer = outer

        def __call__(self, target, *args, **kwargs):
            return self._outer._patch(target, *args, **kwargs)

        def object(self, target, attribute, *args, **kwargs):
            return self._outer.patch_object(target, attribute, *args, **kwargs)

    class _Mocker:
        MagicMock = mock.MagicMock

        def __init__(self) -> None:
            self.patch = _PatchProxy(self)

        def _patch(self, target, *args, **kwargs):
            patcher = mock.patch(target, *args, **kwargs)
            mocked = patcher.start()
            active_patchers.append(patcher)
            return mocked

        def patch_object(self, target, attribute, *args, **kwargs):
            patcher = mock.patch.object(target, attribute, *args, **kwargs)
            mocked = patcher.start()
            active_patchers.append(patcher)
            return mocked

        def spy(self, obj, attribute):
            patcher = mock.patch.object(obj, attribute, wraps=getattr(obj, attribute))
            spy_obj = patcher.start()
            active_patchers.append(patcher)
            return spy_obj

    try:
        yield _Mocker()
    finally:
        while active_patchers:
            active_patchers.pop().stop()

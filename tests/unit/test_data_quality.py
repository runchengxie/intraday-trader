import json
from datetime import datetime

import pandas as pd

from intraday_trader_air.data_quality import (
    build_expected_frequency,
    run_quality_checks,
    write_quality_report,
)


def _build_sample_frame():
    index = pd.date_range("2024-01-02 09:30", periods=5, freq="1min", tz="UTC")
    data = {
        "open": [100, 101, 102, 103, 104],
        "high": [101, 102, 103, 104, 105],
        "low": [99, 100, 101, 102, 103],
        "close": [100, 101, 102, 103, 104],
        "volume": [1000, 1100, 1200, 1300, 1400],
    }
    return pd.DataFrame(data, index=index)


def test_run_quality_checks_passes_on_clean_data():
    df = _build_sample_frame()
    report = run_quality_checks(df, "1min", "TEST")

    assert report["overall_passed"] is True
    assert not report["warnings"]
    assert {check["name"] for check in report["checks"]} == {
        "timestamp_monotonicity",
        "missing_bars",
        "null_values",
        "price_jumps",
    }


def test_run_quality_checks_flags_missing_bar():
    frame = _build_sample_frame()
    df = frame.drop(frame.index[2])
    report = run_quality_checks(df, "1min", "TEST")

    missing_bar_check = next(
        check for check in report["checks"] if check["name"] == "missing_bars"
    )

    assert report["overall_passed"] is False
    assert missing_bar_check["passed"] is False
    assert missing_bar_check["details"]["missing_count"] == 1


def test_write_quality_report(tmp_path):
    df = _build_sample_frame()
    report = run_quality_checks(df, "1min", "TEST")
    report["timestamp"] = datetime(2024, 1, 2, 12, 0, 0).isoformat()

    path = write_quality_report(report, tmp_path)

    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["symbol"] == "TEST"


def test_build_expected_frequency_handles_units():
    assert build_expected_frequency(5, "Minute") == "5min"
    assert build_expected_frequency(2, "hour") == "2H"
    assert build_expected_frequency(1, "DAY") == "1D"
    assert build_expected_frequency(1, "weird") is None

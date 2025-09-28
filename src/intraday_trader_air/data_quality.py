"""Lightweight market data quality control helpers.

The quality checks implemented here intentionally target the minimum
viable set called out in the classroom brief: timestamp monotonicity,
missing bar detection, and large jump alarms.  They are designed to run
inside the ``update-data`` workflow so that every ingestion pass leaves a
traceable QC artefact under ``output/``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QualityCheckResult:
    """Container for a single quality control check."""

    name: str
    passed: bool
    details: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    if not isinstance(df.index, pd.DatetimeIndex):
        index = pd.to_datetime(df.index, utc=True, errors="coerce")
    else:
        index = df.index

    if index.tz is None:
        index = index.tz_localize("UTC")

    return index.sort_values()


def _check_timestamp_monotonic(df: pd.DataFrame) -> QualityCheckResult:
    index = _ensure_datetime_index(df)

    duplicates = int(index.duplicated().sum())
    monotonic = bool(index.is_monotonic_increasing)
    non_monotonic_points = int((np.diff(index.view("i8")) <= 0).sum())

    warnings: list[str] = []
    if duplicates:
        warnings.append(f"Detected {duplicates} duplicated timestamps.")
    if not monotonic:
        warnings.append("Timestamp index is not strictly increasing.")

    return QualityCheckResult(
        name="timestamp_monotonicity",
        passed=monotonic and duplicates == 0 and non_monotonic_points == 0,
        details={
            "duplicates": duplicates,
            "non_monotonic_steps": non_monotonic_points,
        },
        warnings=warnings,
    )


def _check_missing_bars(
    df: pd.DataFrame, expected_frequency: str | None
) -> QualityCheckResult:
    if df.empty:
        return QualityCheckResult(
            name="missing_bars",
            passed=False,
            warnings=["Input dataset is empty."],
            details={"expected_frequency": expected_frequency or "unknown"},
        )

    index = _ensure_datetime_index(df)
    if not expected_frequency:
        # Fall back to inferring the frequency; this is intentionally
        # conservative because irregular intraday data may not infer well.
        inferred = pd.infer_freq(index[:50])
        expected_frequency = inferred if inferred else "infer"

    try:
        expected_range = pd.date_range(index[0], index[-1], freq=expected_frequency)
    except ValueError:
        logger.warning(
            "Unable to build expected index using frequency '%s'", expected_frequency
        )
        expected_range = index

    missing = expected_range.difference(index)
    sample_missing = [ts.isoformat() for ts in missing[:10]]

    warnings: list[str] = []
    if len(missing) > 0:
        warnings.append(
            f"Detected {len(missing)} missing bars relative to {expected_frequency}."
        )

    return QualityCheckResult(
        name="missing_bars",
        passed=len(missing) == 0,
        details={
            "expected_frequency": expected_frequency,
            "missing_count": int(len(missing)),
            "sample_missing": sample_missing,
        },
        warnings=warnings,
    )


def _check_nulls(df: pd.DataFrame) -> QualityCheckResult:
    null_counts = df.isna().sum().to_dict()
    total_nulls = int(sum(null_counts.values()))

    warnings: list[str] = []
    if total_nulls:
        warnings.append(f"Dataset contains {total_nulls} null values across columns.")

    return QualityCheckResult(
        name="null_values",
        passed=total_nulls == 0,
        details={"null_counts": null_counts},
        warnings=warnings,
    )


def _check_price_jumps(df: pd.DataFrame, threshold: float = 0.1) -> QualityCheckResult:
    if "close" not in df.columns:
        return QualityCheckResult(
            name="price_jumps",
            passed=True,
            warnings=["Column 'close' missing; price jump check skipped."],
        )

    closes = df["close"].astype(float)
    pct_change = closes.pct_change().abs()
    spikes = pct_change[pct_change > threshold]

    warnings: list[str] = []
    if not spikes.empty:
        warnings.append(
            f"Found {len(spikes)} price jumps greater than {threshold:.0%}."
        )

    return QualityCheckResult(
        name="price_jumps",
        passed=spikes.empty,
        details={
            "threshold": threshold,
            "spike_examples": [
                {"timestamp": ts.isoformat(), "pct_change": float(val)}
                for ts, val in spikes.head(10).items()
            ],
        },
        warnings=warnings,
    )


def run_quality_checks(
    df: pd.DataFrame,
    expected_frequency: str | None,
    symbol: str,
    *,
    price_jump_threshold: float = 0.1,
) -> dict[str, object]:
    """Execute the default suite of quality checks on ``df``.

    Parameters
    ----------
    df:
        Incoming market data indexed by timestamp.
    expected_frequency:
        Pandas offset alias describing the expected cadence of the bars.
    symbol:
        Trading symbol, only used for logging context.
    price_jump_threshold:
        Absolute percentage move that should trigger a spike warning.
    """

    checks = [
        _check_timestamp_monotonic(df),
        _check_missing_bars(df, expected_frequency),
        _check_nulls(df),
        _check_price_jumps(df, price_jump_threshold),
    ]

    overall_status = all(check.passed for check in checks)
    warnings: list[str] = []
    for check in checks:
        warnings.extend(check.warnings)

    logger.info(
        "Data quality checks for %s completed: %s",
        symbol,
        "passed" if overall_status else "issues detected",
    )

    return {
        "symbol": symbol,
        "timestamp": datetime.utcnow().isoformat(),
        "overall_passed": overall_status,
        "checks": [
            {
                "name": check.name,
                "passed": check.passed,
                "details": check.details,
                "warnings": check.warnings,
            }
            for check in checks
        ],
        "warnings": warnings,
    }


def write_quality_report(report: dict[str, object], output_dir: Path) -> Path:
    """Persist the QC report to ``output_dir`` and return the path."""

    output_dir.mkdir(parents=True, exist_ok=True)
    symbol = report.get("symbol", "unknown")
    timestamp = report.get("timestamp", datetime.utcnow().isoformat())
    suffix = timestamp.replace(":", "").replace("-", "").split(".")[0]
    filename = f"data_qc_{symbol}_{suffix}.json"
    output_path = output_dir / filename

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    logger.info("Wrote data quality report to %s", output_path)
    return output_path


def build_expected_frequency(timeframe_value: int, timeframe_unit: str) -> str | None:
    """Translate the configuration timeframe into a pandas offset alias."""

    unit = timeframe_unit.lower()
    if unit.startswith("min"):
        return f"{timeframe_value}min"
    if unit.startswith("hour"):
        return f"{timeframe_value}H"
    if unit.startswith("day"):
        return f"{timeframe_value}D"
    return None


def summarize_warnings(reports: Iterable[dict[str, object]]) -> list[str]:
    """Flatten warning messages from multiple QC reports."""

    messages: list[str] = []
    for report in reports:
        messages.extend(report.get("warnings", []))
    return messages

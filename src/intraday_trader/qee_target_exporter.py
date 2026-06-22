"""QEE TargetExporter — converts intraday signals to QEE-compatible targets.

Design contract:
  信号 (strategy signal) -> 目标持仓 (target position) -> targets 列表 -> QEE 执行

Signal → target_quantity mapping (long-only, first version):
  BUY   → target_quantity = order_qty
  CLOSE → target_quantity = 0
  SELL  → REJECTED (not supported; log warning, do not execute)
  HOLD  → no targets generated

A SELL signal from a flat position (potential short entry) is explicitly
rejected. The caller is responsible for checking whether SELL is a close
or a short entry before calling this exporter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Signal names as used in intraday-trader
VALID_SIGNALS = frozenset({"BUY", "SELL", "CLOSE", "HOLD"})
EXECUTABLE_SIGNALS = frozenset({"BUY", "CLOSE"})


class TargetExportError(ValueError):
    """Raised when a signal cannot be converted to a valid target."""


def signal_to_targets(
    signal: str,
    *,
    symbol: str,
    market: str = "US",
    order_qty: int | None = None,
    signal_price: float | None = None,
    strategy: str | None = None,
    allow_short: bool = False,
) -> list[dict[str, Any]]:
    """Convert a trading signal into one or more QEE target entries.

    Args:
        signal: One of BUY, SELL, CLOSE, HOLD.
        symbol: Ticker symbol (e.g. ``"AAPL"``).
        market: Market identifier, default ``"US"``.
        order_qty: Target quantity for BUY signals. Required for BUY.
        signal_price: Current market price at signal generation time (metadata only).
        strategy: Strategy name for audit metadata.
        allow_short: If True, SELL from flat position is treated as short entry
                     (NOT YET SUPPORTED by QEE). Default False.

    Returns:
        List of target entry dicts ready for QEEFacade.

    Raises:
        TargetExportError: If the signal cannot be exported (e.g. SELL without
                           allow_short, or BUY without order_qty).
    """
    signal_upper = str(signal).upper().strip()
    if signal_upper not in VALID_SIGNALS:
        raise TargetExportError(
            f"Unknown signal {signal!r}; must be one of {sorted(VALID_SIGNALS)}"
        )

    # HOLD: no targets
    if signal_upper == "HOLD":
        logger.debug("HOLD signal → no targets generated.")
        return []

    # SELL: reject unless allow_short is explicitly True
    if signal_upper == "SELL":
        if allow_short:
            raise TargetExportError(
                "Short selling is not yet supported by quant-execution-engine. "
                "Set allow_short=False and treat SELL as CLOSE only."
            )
        logger.warning(
            "SELL signal received but short-selling is disabled. "
            "If this is a close-position signal, use CLOSE instead."
        )
        return []

    # BUY: require quantity
    if signal_upper == "BUY":
        if order_qty is None or order_qty <= 0:
            raise TargetExportError(
                f"BUY signal requires a positive order_qty, got {order_qty!r}"
            )
        target_quantity = int(order_qty)
    elif signal_upper == "CLOSE":
        target_quantity = 0
    else:
        return []  # unreachable

    entry: dict[str, Any] = {
        "symbol": symbol,
        "market": market,
        "target_quantity": target_quantity,
        "metadata": {
            "strategy": strategy or "unknown",
            "signal": signal_upper,
        },
    }
    if signal_price is not None:
        entry["metadata"]["signal_price"] = signal_price

    logger.info(
        "Signal %s → target %s %s qty=%s",
        signal_upper,
        symbol,
        market,
        target_quantity,
    )
    return [entry]


def export_targets_json(
    targets: list[dict[str, Any]],
    out_path: str,
    *,
    source: str = "intraday-trader",
    asof: str | None = None,
    target_gross_exposure: float = 1.0,
) -> str:
    """Write targets to a JSON file using QEE's canonical writer.

    This function requires ``quant_execution_engine`` to be installed.
    If it's not available, falls back to a plain JSON dump with a warning.

    Args:
        targets: List of target entry dicts.
        out_path: Output file path.
        source: Provenance label.
        asof: ISO-8601 timestamp (defaults to now).
        target_gross_exposure: Gross exposure multiplier.

    Returns:
        The resolved output path as a string.
    """
    import json
    from pathlib import Path

    resolved_asof = asof or datetime.now(timezone.utc).isoformat()

    try:
        from quant_execution_engine.targets import write_targets_json as _qee_write
    except ImportError:
        logger.warning(
            "quant_execution_engine not installed; falling back to plain JSON export."
        )
        payload = {
            "asof": resolved_asof,
            "source": source,
            "target_gross_exposure": target_gross_exposure,
            "targets": targets,
        }
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)

    qee_path = _qee_write(
        out_path=Path(out_path),
        targets=targets,
        source=source,
        asof=resolved_asof,
        target_gross_exposure=target_gross_exposure,
        default_market="US",
    )
    return str(qee_path)

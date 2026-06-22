"""Signal-to-target conversion.

Translates trading signals ("BUY", "SELL", "CLOSE") from the strategy
layer into normalised :class:`SignalTarget` entries that are independent
of any broker or market data provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SignalTarget:
    """A single-target entry produced from a strategy signal.

    This is the first stage in the execution pipeline:
        Signal → SignalTarget → OrderPlan → BrokerAdapter.

    For a single-symbol live loop the target weight is either +1 (BUY),
    -1 (SELL), or 0 (CLOSE / HOLD).  Multi-symbol rebalancing
    (Phase 5) will use fractional weights.
    """

    symbol: str
    market: str
    signal: str  # "BUY" | "SELL" | "CLOSE" | "HOLD"
    target_weight: float = 0.0
    order_qty: int = 0
    signal_price: float | None = None
    strategy: str = ""
    asof: str = ""
    note: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def signal_to_target(
    signal: str,
    *,
    symbol: str,
    market: str = "US",
    order_qty: int = 10,
    signal_price: float | None = None,
    current_position_qty: float = 0.0,
    strategy: str = "",
) -> SignalTarget | None:
    """Convert a trading signal to a :class:`SignalTarget`.

    Returns None for HOLD signals (no action needed).
    """
    signal_upper = signal.upper().strip()

    if signal_upper == "HOLD":
        return None

    if signal_upper == "BUY":
        return SignalTarget(
            symbol=symbol,
            market=market,
            signal="BUY",
            target_weight=1.0,
            order_qty=order_qty,
            signal_price=signal_price,
            strategy=strategy,
            asof=datetime.now(timezone.utc).isoformat(),
            note=f"BUY {order_qty} shares",
        )

    if signal_upper == "SELL":
        # For single-symbol loop: SELL from existing position.
        sell_qty = (
            int(abs(current_position_qty)) if current_position_qty > 0 else order_qty
        )
        return SignalTarget(
            symbol=symbol,
            market=market,
            signal="SELL",
            target_weight=0.0,  # flatten position
            order_qty=sell_qty,
            signal_price=signal_price,
            strategy=strategy,
            asof=datetime.now(timezone.utc).isoformat(),
            note=f"SELL {sell_qty} shares (position={current_position_qty})",
        )

    if signal_upper == "CLOSE":
        return SignalTarget(
            symbol=symbol,
            market=market,
            signal="CLOSE",
            target_weight=0.0,
            order_qty=int(abs(current_position_qty)),
            signal_price=signal_price,
            strategy=strategy,
            asof=datetime.now(timezone.utc).isoformat(),
            note=f"CLOSE position of {current_position_qty} shares",
        )

    # Unknown signal — log and skip.
    return None

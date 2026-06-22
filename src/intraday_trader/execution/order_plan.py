"""Target-to-order-plan conversion.

Translates a :class:`~intraday_trader.execution.targets.SignalTarget`
into a concrete :class:`OrderPlanEntry` ready for broker submission.

Handles:
- Lot-size rounding for non-US markets.
- Limit-price offset (buy markup / sell discount).
- Test-mode safety margins.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor


@dataclass
class OrderPlanEntry:
    """A single order ready for broker submission.

    All fields are concrete — no further logic needed before calling
    ``broker.place_order(**kwargs)``.
    """

    symbol: str
    side: str         # "buy" | "sell"
    qty: float
    order_type: str   # "market" | "limit"
    limit_price: float | None = None
    time_in_force: str = "day"
    client_order_id: str = ""

    # Audit trail
    signal: str = ""
    market_price: float | None = None
    lot_size: int = 1
    note: str = ""


@dataclass
class OrderPlanOptions:
    """Configurable parameters for the order-plan builder."""

    lot_size: int = 1
    buy_markup_bps: float = 5.0  # basis points above market for buy limit
    sell_discount_bps: float = 5.0  # basis points below market for sell limit
    default_order_type: str = "market"
    time_in_force: str = "day"


def build_order_plan(
    target,
    *,
    current_price: float,
    options: OrderPlanOptions | None = None,
    is_test_mode: bool = False,
    test_price_offset_pct: float = 0.10,
    client_order_id_prefix: str = "live",
) -> OrderPlanEntry:
    """Build a single order from a :class:`SignalTarget`.

    Args:
        target: The signal-to-target conversion result.
        current_price: Current market price used for limit calculations.
        options: Lot size, markup/discount, and order type defaults.
        is_test_mode: If True, offset limit prices to avoid fills.
        test_price_offset_pct: How far to offset prices in test mode (default 10%).
        client_order_id_prefix: Prefix for the generated client_order_id.
    """
    import uuid

    opts = options or OrderPlanOptions()

    side = "buy" if target.signal == "BUY" else "sell"
    order_type = opts.default_order_type

    # Lot-size rounding for quantity.
    qty = _round_to_lot(target.order_qty, opts.lot_size)

    # Determine limit price.
    limit_price: float | None = None
    market_price = current_price

    if order_type == "limit" or is_test_mode:
        if is_test_mode:
            # Test mode: offset price AWAY from market so orders don't fill.
            if side == "buy":
                limit_price = round(current_price * (1 - test_price_offset_pct), 4)
            else:
                limit_price = round(current_price * (1 + test_price_offset_pct), 4)
        elif side == "buy":
            limit_price = round(
                current_price * (1 + opts.buy_markup_bps / 10000.0), 4
            )
        else:
            limit_price = round(
                current_price * (1 - opts.sell_discount_bps / 10000.0), 4
            )

    client_order_id = (
        f"{'no-fill-test' if is_test_mode else client_order_id_prefix}"
        f"_{uuid.uuid4()}"
    )

    return OrderPlanEntry(
        symbol=target.symbol,
        side=side,
        qty=float(qty),
        order_type="limit" if limit_price is not None else order_type,
        limit_price=limit_price,
        time_in_force=opts.time_in_force,
        client_order_id=client_order_id,
        signal=target.signal,
        market_price=market_price,
        lot_size=opts.lot_size,
        note=target.note,
    )


def build_close_plan(
    symbol: str,
    current_position_qty: float,
    current_price: float,
    *,
    is_test_mode: bool = False,
) -> OrderPlanEntry:
    """Build a market order to close an existing position.

    When the broker supports ``close_position`` directly, that is
    preferred.  This function provides a market-order fallback.
    """
    import uuid

    abs_qty = abs(current_position_qty)
    side = "sell" if current_position_qty > 0 else "buy"

    return OrderPlanEntry(
        symbol=symbol,
        side=side,
        qty=float(abs_qty),
        order_type="market",
        time_in_force="day",
        client_order_id=f"{'no-fill-test' if is_test_mode else 'live'}_{uuid.uuid4()}",
        signal="CLOSE",
        market_price=current_price,
        note=f"CLOSE position of {current_position_qty} shares",
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _round_to_lot(qty: int, lot_size: int) -> int:
    if lot_size <= 1:
        return max(1, qty)
    return max(lot_size, int(floor(qty / lot_size) * lot_size))

"""Order-plan executor.

Takes an :class:`~intraday_trader.execution.order_plan.OrderPlanEntry`
and submits it through the configured :class:`BrokerAdapter`.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def execute_order_plan(
    plan_entry,
    broker,
) -> dict[str, Any]:
    """Submit a single :class:`OrderPlanEntry` through *broker*.

    Returns a dict with keys:
        order (StandardOrder | None): the created order, or None on failure.
        error (str | None): error message if the order was rejected.
        plan: the original OrderPlanEntry for audit.

    The caller is responsible for tracking the order ID and scheduling
    post-order reconciliation.
    """
    logger.info(
        "Executing order plan: %s %s %s @ %s (limit=%s, tif=%s)",
        plan_entry.side,
        plan_entry.qty,
        plan_entry.symbol,
        plan_entry.order_type,
        plan_entry.limit_price,
        plan_entry.time_in_force,
    )

    kwargs: dict[str, Any] = {
        "symbol": plan_entry.symbol,
        "qty": plan_entry.qty,
        "side": plan_entry.side,
        "order_type": plan_entry.order_type,
        "time_in_force": plan_entry.time_in_force,
        "client_order_id": plan_entry.client_order_id,
    }
    if plan_entry.limit_price is not None:
        kwargs["limit_price"] = plan_entry.limit_price

    try:
        order = broker.place_order(**kwargs)
    except Exception as exc:
        logger.exception("place_order raised: %s", exc)
        return {"order": None, "error": str(exc), "plan": plan_entry}

    if order is None:
        logger.error(
            "place_order returned None for %s %s", plan_entry.symbol, plan_entry.signal
        )
        return {"order": None, "error": "place_order returned None", "plan": plan_entry}

    order_id = getattr(order, "id", getattr(order, "order_id", "unknown"))
    logger.info(
        "Order submitted: id=%s, status=%s", order_id, getattr(order, "status", "?")
    )

    return {"order": order, "error": None, "plan": plan_entry}


def execute_close_via_order(
    broker,
    symbol: str,
    current_position_qty: float,
    current_price: float,
) -> dict[str, Any]:
    """Close an existing position via a market order.

    Prefer ``broker.close_position()`` when available (Alpaca); this is
    the market-order fallback for brokers that don't support it.
    """
    from .order_plan import build_close_plan

    plan = build_close_plan(symbol, current_position_qty, current_price)
    logger.info(
        "Closing position %s (%s shares) via market order", symbol, current_position_qty
    )
    return execute_order_plan(plan, broker)

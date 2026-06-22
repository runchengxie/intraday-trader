"""Alpaca broker adapter.

Wraps the existing ``BrokerAPIHandler`` and translates all return values
to :class:`~intraday_trader.brokers.protocols.StandardOrder`,
:class:`~intraday_trader.brokers.protocols.StandardAccount`, and
:class:`~intraday_trader.brokers.protocols.StandardPosition`.

Stream methods (``setup_stream``, ``start_streaming``, ``stop_streaming``)
are pass-through to the underlying handler; they still return / receive
Alpaca-native objects.  Callers that need streaming should duck-type
those methods for now.
"""

from __future__ import annotations

import logging
from typing import Any

from intraday_trader.broker_handler import BrokerAPIHandler

from .protocols import StandardAccount, StandardOrder, StandardPosition

logger = logging.getLogger(__name__)


class AlpacaBrokerAdapter:
    """Broker adapter that speaks Alpaca REST and translates to standard types."""

    def __init__(self) -> None:
        self._handler = BrokerAPIHandler()

    # -- account -----------------------------------------------------------

    def get_account(self) -> StandardAccount | None:
        acc = self._handler.get_account_info()
        if acc is None:
            return None
        return StandardAccount(
            account_id=str(acc.id),
            cash=float(acc.cash),
            portfolio_value=float(acc.portfolio_value),
            buying_power=float(acc.buying_power),
            currency=str(getattr(acc, "currency", "USD")),
            status=str(getattr(acc, "status", "ACTIVE")),
        )

    # -- positions ---------------------------------------------------------

    def get_position(self, symbol: str) -> StandardPosition | None:
        pos = self._handler.get_position(symbol)
        if pos is None:
            return None
        return StandardPosition(
            symbol=symbol,
            qty=float(pos.qty),
            avg_entry_price=float(getattr(pos, "avg_entry_price", 0) or 0),
            market_value=float(getattr(pos, "market_value", 0) or 0),
            current_price=float(getattr(pos, "current_price", 0) or 0),
        )

    def list_positions(self) -> list[StandardPosition]:
        positions = self._handler.list_positions()
        result: list[StandardPosition] = []
        for pos in positions:
            result.append(
                StandardPosition(
                    symbol=str(pos.symbol),
                    qty=float(pos.qty),
                    avg_entry_price=float(getattr(pos, "avg_entry_price", 0) or 0),
                    market_value=float(getattr(pos, "market_value", 0) or 0),
                    current_price=float(getattr(pos, "current_price", 0) or 0),
                )
            )
        return result

    # -- orders ------------------------------------------------------------

    def place_order(self, **kwargs: Any) -> StandardOrder | None:
        order = self._handler.place_order(**kwargs)
        if order is None:
            return None
        return _alpaca_order_to_standard(order)

    def get_order(self, order_id: str) -> StandardOrder | None:
        order = self._handler.get_order_status(order_id)
        if order is None:
            return None
        return _alpaca_order_to_standard(order)

    def cancel_order(self, order_id: str) -> bool:
        return self._handler.cancel_order(order_id)

    def cancel_all_orders(self) -> bool:
        return self._handler.cancel_all_orders()

    # -- stream (pass-through to underlying handler) -----------------------

    async def setup_stream(self, **kwargs: Any) -> bool:
        """Pass-through to Alpaca stream setup."""
        return await self._handler.setup_stream(**kwargs)

    async def start_streaming(self) -> None:
        """Pass-through to Alpaca stream runner."""
        await self._handler.start_streaming()

    async def stop_streaming(self) -> None:
        """Pass-through to Alpaca stream stopper."""
        await self._handler.stop_streaming()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _alpaca_order_to_standard(order: Any) -> StandardOrder:
    """Convert an Alpaca order object to :class:`StandardOrder`."""
    return StandardOrder(
        order_id=str(order.id),
        client_order_id=getattr(order, "client_order_id", None),
        symbol=str(order.symbol),
        side=str(order.side),
        qty=float(order.qty),
        order_type=str(getattr(order, "type", order.order_type)),
        status=str(order.status),
        filled_qty=float(getattr(order, "filled_qty", 0) or 0),
        filled_price=(
            float(order.filled_avg_price)
            if getattr(order, "filled_avg_price", None)
            else None
        ),
        limit_price=(
            float(order.limit_price) if getattr(order, "limit_price", None) else None
        ),
        stop_price=(
            float(order.stop_price) if getattr(order, "stop_price", None) else None
        ),
        time_in_force=str(getattr(order, "time_in_force", "day")),
        created_at=str(getattr(order, "created_at", "") or ""),
        updated_at=str(getattr(order, "updated_at", "") or ""),
    )

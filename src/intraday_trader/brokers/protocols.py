"""Unified broker protocol and standard data models.

All broker adapters return these standard objects.  Strategy and risk layers
never see Alpaca objects or Futu DataFrames — they only see these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Standard data models
# ---------------------------------------------------------------------------


@dataclass
class StandardAccount:
    """Broker-agnostic account summary."""

    account_id: str
    cash: float
    portfolio_value: float
    buying_power: float
    currency: str = "USD"
    status: str = "ACTIVE"


@dataclass
class StandardPosition:
    """Broker-agnostic position for a single symbol."""

    symbol: str
    qty: float
    avg_entry_price: float | None = None
    market_value: float | None = None
    current_price: float | None = None


@dataclass
class StandardOrder:
    """Broker-agnostic order snapshot.

    The ``id`` property aliases ``order_id`` for backward compatibility
    with callers that expect ``order_result.id`` (Alpaca convention).
    """

    order_id: str
    client_order_id: str | None
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    order_type: str  # "market" | "limit" | "stop" | ...
    status: str  # "filled" | "canceled" | "rejected" | "expired" | "open" | ...
    filled_qty: float = 0.0
    filled_price: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "day"
    created_at: str | None = None
    updated_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Alias for *order_id* (Alpaca compatibility)."""
        return self.order_id


# ---------------------------------------------------------------------------
# Broker adapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class BrokerAdapter(Protocol):
    """Protocol that every broker adapter must satisfy.

    Phase 1 covers REST methods only.  Stream methods (setup_stream,
    start_streaming, stop_streaming) are NOT on this protocol yet because
    Alpaca and Futu have fundamentally different push models.  Callers that
    need streaming currently access the adapter by name or duck-type the
    stream methods directly.
    """

    # -- account ---------------------------------------------------------

    def get_account(self) -> StandardAccount | None:
        """Return current account summary."""
        ...

    # -- positions -------------------------------------------------------

    def get_position(self, symbol: str) -> StandardPosition | None:
        """Return position for *symbol*, or None if no position held."""
        ...

    def list_positions(self) -> list[StandardPosition]:
        """Return all open positions."""
        ...

    # -- orders ----------------------------------------------------------

    def place_order(self, **kwargs: Any) -> StandardOrder | None:
        """Submit a new order.  Returns the created order or None on failure.

        Expected kwargs:
            symbol (str)
            qty (float)          - positive quantity
            side (str)           - "buy" | "sell"
            order_type (str)     - "market" | "limit" | ...
            time_in_force (str)  - "day" | "gtc" | ...
            limit_price (float | None)
            stop_price (float | None)
            client_order_id (str | None)
        """
        ...

    def get_order(self, order_id: str) -> StandardOrder | None:
        """Look up an order by broker-assigned order_id."""
        ...

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.  Returns True if cancellation was accepted."""
        ...

    def cancel_all_orders(self) -> bool:
        """Cancel every open order."""
        ...

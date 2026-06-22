"""Futu / FutuOpenD broker adapter.

Uses ``futu-api`` to connect to a locally running FutuOpenD gateway.
All return values are :class:`~intraday_trader.brokers.protocols.Standard*`
objects.

Stream methods are NOT implemented in Phase 1 (Alpaca and Futu push
models differ too much).  The live trading loop currently falls back to
REST polling for Futu.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from .protocols import StandardAccount, StandardOrder, StandardPosition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Futu → Standard status mapping
# ---------------------------------------------------------------------------

# Futu order status constants (from futu.OrderStatus)
_FUTU_STATUS_MAP: dict[str, str] = {
    "SUBMITTING": "open",
    "SUBMITTED": "open",
    "FILLED_PART": "open",       # partial fill → still open
    "FILLED_ALL": "filled",
    "CANCELLED_PART": "canceled",
    "CANCELLED_ALL": "canceled",
    "FAILED": "rejected",
    "DISABLED": "canceled",
    "DELETED": "canceled",
}

# ---------------------------------------------------------------------------
# Connection config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FutuConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 11111
    trd_env: str = "SIMULATE"   # "SIMULATE" | "REAL"
    market: str = "HK"          # "HK" | "US" | "CN"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class FutuBrokerAdapter:
    """Broker adapter for FutuOpenD.

    Phase 1 limitations:
    - SIMULATE trading environment only (REAL gated behind unlock password).
    - No streaming support; callers should use REST polling.
    - Orders are submitted as ``OrderType.NORMAL`` (limit-like).
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        trd_env: str | None = None,
        market: str | None = None,
    ) -> None:
        # Resolve config from env vars, falling back to constructor args.
        resolved_host = host or os.getenv("FUTU_HOST", "127.0.0.1")
        resolved_port = int(port or os.getenv("FUTU_PORT", "11111"))
        resolved_env = (trd_env or os.getenv("FUTU_TRD_ENV", "SIMULATE")).upper()
        resolved_market = (market or os.getenv("FUTU_MARKET", "HK")).upper()

        self._cfg = FutuConnectionConfig(
            host=resolved_host,
            port=resolved_port,
            trd_env=resolved_env,
            market=resolved_market,
        )

        # Lazy imports so the module is importable without futu-api installed.
        from futu import (
            RET_OK,
            Currency,
            OpenQuoteContext,
            OpenSecTradeContext,
            TrdEnv,
        )

        self._RET_OK = RET_OK
        self._Currency = Currency
        self._TrdEnv = getattr(TrdEnv, self._cfg.trd_env)
        self._currency = Currency.HKD if resolved_market == "HK" else Currency.USD

        logger.info(
            "Connecting to FutuOpenD at %s:%s (env=%s, market=%s)",
            self._cfg.host,
            self._cfg.port,
            self._cfg.trd_env,
            self._cfg.market,
        )

        self._trade_ctx = OpenSecTradeContext(
            host=self._cfg.host, port=self._cfg.port
        )
        self._quote_ctx = OpenQuoteContext(
            host=self._cfg.host, port=self._cfg.port
        )

        # Security gate: REAL requires unlock password.
        if self._TrdEnv == TrdEnv.REAL:
            self._unlock_trade()

    def __del__(self) -> None:
        try:
            if hasattr(self, "_quote_ctx") and self._quote_ctx:
                self._quote_ctx.close()
        except Exception:
            pass
        try:
            if hasattr(self, "_trade_ctx") and self._trade_ctx:
                self._trade_ctx.close()
        except Exception:
            pass

    # -- account -----------------------------------------------------------

    def get_account(self) -> StandardAccount | None:
        ret, acc_df = self._trade_ctx.accinfo_query(
            trd_env=self._TrdEnv, currency=self._currency
        )
        if ret != self._RET_OK or acc_df is None or acc_df.empty:
            logger.error("accinfo_query failed: %s", acc_df)
            return None

        row = acc_df.iloc[0]
        cash_col = "cash" if "cash" in acc_df.columns else "cash_balance"
        return StandardAccount(
            account_id=str(row.get("acc_id", "futu")),
            cash=float(row.get(cash_col, 0) or 0),
            portfolio_value=float(row.get("total_assets", 0) or 0),
            buying_power=float(row.get("buying_power", 0) or 0),
            currency=self._currency.name,
            status="ACTIVE",
        )

    # -- positions ---------------------------------------------------------

    def get_position(self, symbol: str) -> StandardPosition | None:
        futu_code = _to_futu_code(symbol, self._cfg.market)
        ret, pos_df = self._trade_ctx.position_list_query(trd_env=self._TrdEnv)
        if ret != self._RET_OK or pos_df is None or pos_df.empty:
            return None

        row = pos_df[pos_df["code"] == futu_code]
        if row.empty:
            return None
        r = row.iloc[0]
        return StandardPosition(
            symbol=futu_code,
            qty=float(r["qty"]),
            avg_entry_price=float(r.get("cost_price", 0) or 0),
            market_value=float(r.get("market_val", 0) or 0),
            current_price=float(r.get("nominal_price", 0) or 0),
        )

    def list_positions(self) -> list[StandardPosition]:
        ret, pos_df = self._trade_ctx.position_list_query(trd_env=self._TrdEnv)
        if ret != self._RET_OK or pos_df is None or pos_df.empty:
            return []

        result: list[StandardPosition] = []
        for _, row in pos_df.iterrows():
            result.append(
                StandardPosition(
                    symbol=str(row["code"]),
                    qty=float(row["qty"]),
                    avg_entry_price=float(row.get("cost_price", 0) or 0),
                    market_value=float(row.get("market_val", 0) or 0),
                    current_price=float(row.get("nominal_price", 0) or 0),
                )
            )
        return result

    # -- orders ------------------------------------------------------------

    def place_order(self, **kwargs: Any) -> StandardOrder | None:
        """Submit an order to Futu.

        Supported kwargs:
            symbol (str)      — ticker, will be formatted to Futu code
            qty (float)       — positive share quantity
            side (str)        — "buy" | "sell"
            order_type (str)  — "market" | "limit" (others rejected)
            limit_price (float | None)
        """
        from futu import OrderType, TrdSide

        symbol = str(kwargs.get("symbol", ""))
        qty = abs(int(float(kwargs.get("qty", 0))))
        side = str(kwargs.get("side", "buy")).lower()
        order_type = str(kwargs.get("order_type", "market")).lower()
        limit_price = kwargs.get("limit_price")
        client_order_id = kwargs.get("client_order_id")

        if not symbol:
            logger.error("place_order: symbol is required")
            return None
        if qty == 0:
            logger.error("place_order: qty must be positive")
            return None

        # Order type mapping — only market / limit in Phase 1.
        if order_type not in ("market", "limit"):
            logger.error(
                "place_order: unsupported order_type=%r (only market/limit in Phase 1)",
                order_type,
            )
            return None

        if order_type == "limit" and limit_price is None:
            logger.error("place_order: limit_price required for limit orders")
            return None

        futu_code = _to_futu_code(symbol, self._cfg.market)
        trd_side = TrdSide.BUY if side == "buy" else TrdSide.SELL

        # For market orders on Futu: pass price=0 with OrderType.MARKET.
        # For limit orders: pass the limit price with OrderType.NORMAL.
        if order_type == "market":
            price = 0.0
            futu_order_type = OrderType.MARKET
        else:
            price = float(limit_price)  # type: ignore[arg-type]
            futu_order_type = OrderType.NORMAL

        ret, data = self._trade_ctx.place_order(
            price=price,
            qty=qty,
            code=futu_code,
            trd_side=trd_side,
            order_type=futu_order_type,
            trd_env=self._TrdEnv,
            remark=client_order_id or "",
        )

        if ret != self._RET_OK:
            logger.error("place_order failed: %s", data)
            return None

        # data is a DataFrame with one row containing order details.
        if data is None or data.empty:
            logger.error("place_order returned empty result")
            return None

        try:
            row = data.iloc[0]
            return StandardOrder(
                order_id=str(row.get("order_id", "")),
                client_order_id=client_order_id,
                symbol=futu_code,
                side=side,
                qty=float(qty),
                order_type=order_type,
                status=_map_futu_status(str(row.get("order_status", "SUBMITTED"))),
                filled_qty=float(row.get("dealt_qty", 0) or 0),
                filled_price=(
                    float(row["dealt_avg_price"])
                    if row.get("dealt_avg_price") and float(row["dealt_avg_price"]) > 0
                    else None
                ),
                limit_price=limit_price if order_type == "limit" else None,
                time_in_force="day",
                extra={"futu_order_id": str(row.get("order_id", ""))},
            )
        except Exception:
            logger.exception("Failed to parse place_order result")
            return None

    def get_order(self, order_id: str) -> StandardOrder | None:
        """Look up an order by Futu order_id via order_list_query."""
        from futu import OrderStatus

        # order_list_query with status_filter=OrderStatus.ALL returns all orders.
        ret, orders_df = self._trade_ctx.order_list_query(
            status_filter=OrderStatus.ALL, trd_env=self._TrdEnv
        )
        if ret != self._RET_OK or orders_df is None or orders_df.empty:
            logger.error("order_list_query failed: %s", orders_df)
            return None

        row = orders_df[orders_df["order_id"].astype(str) == str(order_id)]
        if row.empty:
            return None

        try:
            r = row.iloc[0]
            futu_status = str(r.get("order_status", ""))
            return StandardOrder(
                order_id=str(r["order_id"]),
                client_order_id=str(r.get("remark", "") or ""),
                symbol=str(r.get("code", "")),
                side="buy" if str(r.get("trd_side", "")).upper() == "BUY" else "sell",
                qty=float(r.get("qty", 0)),
                order_type="limit" if r.get("price", 0) else "market",
                status=_map_futu_status(futu_status),
                filled_qty=float(r.get("dealt_qty", 0) or 0),
                filled_price=(
                    float(r["dealt_avg_price"])
                    if r.get("dealt_avg_price") and float(r["dealt_avg_price"]) > 0
                    else None
                ),
                limit_price=float(r["price"]) if r.get("price") else None,
                time_in_force="day",
                extra={"futu_status": futu_status},
            )
        except Exception:
            logger.exception("Failed to parse get_order result")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by modifying its status.

        Futu OpenD does not have a dedicated cancel_order API.  Instead
        we use ``modify_order`` with ``modify_order_op=MODIFY_ORDER_CANCEL``.
        """
        from futu import ModifyOrderOp

        ret, data = self._trade_ctx.modify_order(
            modify_order_op=ModifyOrderOp.CANCEL,
            order_id=str(order_id),
            qty=0,
            price=0,
            trd_env=self._TrdEnv,
        )
        if ret != self._RET_OK:
            logger.error("cancel_order(%s) failed: %s", order_id, data)
            return False
        return True

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders.  Best-effort."""
        from futu import OrderStatus

        ret, orders_df = self._trade_ctx.order_list_query(
            status_filter=OrderStatus.SUBMITTED, trd_env=self._TrdEnv
        )
        if ret != self._RET_OK or orders_df is None or orders_df.empty:
            # No open orders.
            return True

        success = True
        for _, row in orders_df.iterrows():
            oid = str(row["order_id"])
            if not self.cancel_order(oid):
                success = False
        return success

    # -- internals ---------------------------------------------------------

    def _unlock_trade(self) -> None:
        password = os.getenv("FUTU_UNLOCK_PWD", "").strip()
        if not password:
            raise ValueError(
                "FUTU_UNLOCK_PWD is required for REAL trading. "
                "Set it in your environment or use mode='simulate'."
            )
        ret, data = self._trade_ctx.unlock_trade(password=password)
        if ret != self._RET_OK:
            raise RuntimeError(f"unlock_trade failed: {data}")
        logger.info("Futu REAL trade unlocked successfully.")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _to_futu_code(symbol: str, market: str) -> str:
    """Format a ticker to the Futu code convention (e.g. ``US.AAPL``)."""
    s = symbol.upper().strip()
    if "." in s:
        return s  # Already prefixed (US.AAPL, HK.00700, SH.600000, etc.)
    if market == "US":
        return f"US.{s}"
    if market == "HK":
        return f"HK.{s}"
    if market == "CN":
        return f"SH.{s}" if s.startswith("6") else f"SZ.{s}"
    return s


def _map_futu_status(futu_status: str) -> str:
    """Map a Futu order status string to our standard status."""
    return _FUTU_STATUS_MAP.get(futu_status.upper(), "open")

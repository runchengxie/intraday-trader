import asyncio
import logging
import os
import random
from datetime import datetime, timezone

import numpy as np
import websockets

from intraday_trader.brokers import create_broker
from intraday_trader.consistency_validator import ConsistencyValidator
from intraday_trader.exception_handler import (
    ErrorCategory,
    ErrorSeverity,
    ExceptionHandler,
    handle_exceptions,
)
from intraday_trader.execution import (
    OrderPlanOptions,
    build_order_plan,
    execute_close_via_order,
    execute_order_plan,
    signal_to_target,
)
from intraday_trader.live_components import (
    LiveMeanReversionStrategy,
    TradingState,
)
from intraday_trader.performance_analyzer import PerformanceAnalyzer

# Import core modules
from intraday_trader.risk_manager import RiskManager

# Logger will be configured in main() after loading config
logger = logging.getLogger(__name__)

# Re-export for entry-point backward compatibility (pyproject.toml: run-live)
from intraday_trader.live.session import main  # noqa: F401


class EnhancedTradingSystem:
    """
    Enhanced Trading System - Refactored
    Uses only BrokerAPIHandler for all interactions, following the correct live trading pattern.
    """

    def __init__(self, app_config: dict, db_handler=None):
        self.app_config = app_config
        self.db_handler = db_handler

        # Get initial capital from config
        initial_capital = self.app_config.get("live_trading", {}).get(
            "initial_capital", 100000
        )

        # Initialize core components
        # --- MODIFICATION: Pass risk config to RiskManager ---
        live_trading_config = self.app_config.get("live_trading", {})
        risk_config = live_trading_config.get("risk_limits", {})

        self.risk_manager = RiskManager(risk_config=risk_config)

        self.performance_analyzer = PerformanceAnalyzer(initial_capital=initial_capital)

        self.exception_handler = ExceptionHandler()
        self.consistency_validator = ConsistencyValidator()

        # Initialize trading components - ONLY broker_handler, no redundant WebSocket
        self.broker_handler = None
        self.trading_strategy = None
        self.trading_state = TradingState(
            symbol=self.app_config.get("live_trading", {}).get("symbol", "AAPL")
        )

        # Data storage
        self.trade_history = []
        self.signal_history = []

        # Asyncio queue for data processing
        self.data_queue = None

        # Performance monitoring task
        self.performance_monitor_task = None
        self._stop_requested = asyncio.Event()

        # QEE execution backend (lazy, only used when execution.backend == "qee")
        self.qee_backend = None
        execution_cfg = live_trading_config.get("execution", {})
        if isinstance(execution_cfg, dict) and execution_cfg.get("backend") == "qee":
            from intraday_trader.qee_execution_backend import QEEExecutionBackend

            self.qee_backend = QEEExecutionBackend(config=execution_cfg.get("qee", {}))

        logger.info("Enhanced trading system initialization completed")

    async def _auto_cancel_test_order(self, order_id: str, delay_seconds: int):
        """Automatically cancel a test order after the specified delay"""
        try:
            await asyncio.sleep(delay_seconds)
            logger.info(
                f"[NO-FILL-TEST] Auto-canceling test order {order_id} after {delay_seconds} seconds"
            )

            # Cancel the order
            cancel_result = self.broker_handler.cancel_order(order_id)
            if cancel_result:
                logger.info(
                    f"[NO-FILL-TEST] Successfully canceled test order {order_id}"
                )
            else:
                logger.warning(f"[NO-FILL-TEST] Failed to cancel test order {order_id}")

        except Exception as e:
            logger.error(f"[NO-FILL-TEST] Error auto-canceling order {order_id}: {e}")

    async def _post_order_reconciliation(
        self,
        order_id: str,
        *,
        baseline_cash: float | None,
        baseline_position: float,
        side: str,
        reference_price: float,
        is_test_mode: bool,
    ):
        """Run a focused reconciliation cycle shortly after submitting an order."""

        await asyncio.sleep(2)  # give the broker stream a moment to respond

        try:
            order_info = await asyncio.to_thread(
                self.broker_handler.get_order, order_id
            )
            account_info = await asyncio.to_thread(self.broker_handler.get_account)
            position_info = await asyncio.to_thread(
                self.broker_handler.get_position, self.trading_state.symbol
            )
        except Exception as exc:  # pragma: no cover - network paths are hard to mock
            logger.error(
                f"[RECONCILE] Failed to pull reconciliation snapshots for order {order_id}: {exc}"
            )
            return

        filled_qty = (
            float(getattr(order_info, "filled_qty", 0.0)) if order_info else 0.0
        )
        order_status = (
            getattr(order_info, "status", "unknown") if order_info else "missing"
        )
        account_cash = (
            float(getattr(account_info, "cash", baseline_cash or 0.0))
            if account_info
            else baseline_cash
        )
        position_qty = (
            float(getattr(position_info, "qty", baseline_position))
            if position_info
            else baseline_position
        )

        logger.info(
            f"[RECONCILE] Post-order snapshot for {order_id}: status={order_status}, filled={filled_qty}, "
            f"cash={account_cash}, position={position_qty}"
        )

        tolerance = 0.01
        cash_delta = (
            abs((baseline_cash or 0.0) - account_cash)
            if baseline_cash is not None and account_cash is not None
            else 0.0
        )
        position_delta = abs(position_qty - baseline_position)

        if is_test_mode:
            if filled_qty > 0 or cash_delta > tolerance or position_delta > tolerance:
                logger.warning(
                    "[NO-FILL-TEST] Unexpected state change detected after test order %s (cash Δ=%s, position Δ=%s, filled=%s)",
                    order_id,
                    f"{cash_delta:.2f}" if cash_delta is not None else "n/a",
                    f"{position_delta:.2f}",
                    filled_qty,
                )
            else:
                logger.info(
                    f"[NO-FILL-TEST] Reconciliation confirmed no state change for test order {order_id}."
                )

        if filled_qty > 0 and position_delta < tolerance:
            logger.warning(
                "[RECONCILE] Partial fill reported for %s but position unchanged; triggering consistency validator.",
                order_id,
            )
            synthetic_backtest = {
                "trades": [
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "symbol": self.trading_state.symbol,
                        "side": side.lower(),
                        "quantity": 0.0,
                        "price": reference_price,
                    }
                ]
            }
            synthetic_live = {
                "trades": [
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "symbol": self.trading_state.symbol,
                        "side": side.lower(),
                        "quantity": filled_qty,
                        "price": reference_price,
                    }
                ]
            }

            results = self.consistency_validator.validate_consistency(
                synthetic_backtest,
                synthetic_live,
                test_names=["ExecutionConsistencyTest"],
            )

            exec_result = results.get("ExecutionConsistencyTest")
            if exec_result and exec_result.warnings:
                for warning in exec_result.warnings:
                    logger.warning(
                        f"[RECONCILE] Consistency validator warning for {order_id}: {warning}"
                    )

    async def _monitor_performance(self):
        """Periodically monitor and log performance"""
        while True:
            try:
                if self.db_handler:
                    portfolio_value = self.trading_state.get_portfolio_value()
                    snapshot = {
                        "timestamp": datetime.now(),
                        "portfolio_value": portfolio_value,
                        "cash": self.trading_state.last_known_cash,
                        "positions": self.trading_state.get_positions(),
                    }
                    await self.db_handler.log_performance_snapshot(snapshot)
                    logger.debug(f"Performance snapshot logged: {snapshot}")
                await asyncio.sleep(60)  # Log every minute
            except Exception as e:
                logger.error(f"Error in performance monitoring: {e}")
                await asyncio.sleep(5)  # Wait before retrying

    @handle_exceptions(ErrorCategory.SYSTEM, ErrorSeverity.HIGH)
    def initialize_components(self):
        """
        Initialize all components - using ONLY broker_handler
        """
        logger.info("Starting to initialize trading components...")

        try:
            # Initialize broker adapter via factory (Phase 1: multi-broker)
            self.broker_handler = create_broker(self.app_config)

            # Initialize trading strategy with correct parameter mapping
            strategy_config = (
                self.app_config.get("strategies", {})
                .get("mean_reversion", {})
                .get("params", {})
            )
            live_trading_config = self.app_config.get("live_trading", {})

            self.trading_strategy = LiveMeanReversionStrategy(
                symbol=live_trading_config.get("symbol", "AAPL"),
                zscore_period=strategy_config.get("zscore_period", 20),
                zscore_upper=strategy_config.get("zscore_upper", 2.0),
                zscore_lower=strategy_config.get("zscore_lower", -2.0),
                exit_threshold=strategy_config.get("exit_threshold", 0.0),
            )

            # Initialize asyncio queue
            self.data_queue = asyncio.Queue()

            # Register exception handling callbacks
            self._register_error_callbacks()

            logger.info("All components initialized successfully")

        except Exception as e:
            logger.error(f"Component initialization failed: {e}")
            raise

    def _register_error_callbacks(self):
        """
        Register error handling callbacks
        """

        def on_network_error(error_record):
            logger.warning(f"Network error handling: {error_record.message}")

        def on_api_error(error_record):
            logger.warning(f"API error handling: {error_record.message}")

        def on_order_error(error_record):
            logger.error(f"Order error handling: {error_record.message}")

        self.exception_handler.register_error_callback(
            ErrorCategory.NETWORK, on_network_error
        )
        self.exception_handler.register_error_callback(ErrorCategory.API, on_api_error)
        self.exception_handler.register_error_callback(
            ErrorCategory.ORDER_EXECUTION, on_order_error
        )

    async def handle_trade_update(self, update_data: dict):
        """Handle trade updates from broker with comprehensive logging"""
        try:
            order_id = update_data.get("order_id")
            order_status = update_data.get("status")
            filled_qty = float(update_data.get("filled_qty", 0))
            filled_price = float(update_data.get("filled_price", 0))
            remaining_qty = float(update_data.get("remaining_qty", 0))
            client_order_id = update_data.get("client_order_id")

            # Enhanced WebSocket event logging as requested
            logger.info(
                f"[WebSocket EVENT] Order ID: {order_id}, Status: {order_status}"
            )
            logger.info(
                f"[WebSocket EVENT] Full update - Order ID: {order_id}, Status: {order_status}, "
                f"Client ID: {client_order_id}, Filled: {filled_qty} @ {filled_price}, Remaining: {remaining_qty}"
            )

            # Check if this is a test order
            is_test_order = client_order_id and "no-fill-test" in client_order_id
            if is_test_order:
                logger.info(
                    f"[NO-FILL-TEST] [WebSocket EVENT] Test order update: {order_id} -> {order_status}"
                )

            # Update stream status in trading state for reconciliation
            if order_id:
                import time

                self.trading_state.update_stream_order_status(
                    order_id, order_status, time.time()
                )
                logger.debug(
                    f"[WebSocket EVENT] Updated stream status for order {order_id}: {order_status}"
                )

            # Update active order tracking
            if order_status in ["filled", "canceled", "expired", "rejected"]:
                if order_id == self.trading_state.active_order_id:
                    logger.info(
                        f"[WebSocket EVENT] Order {order_id} reached terminal state: {order_status}"
                    )
                    self.trading_state.clear_active_order()
                    logger.info(
                        f"[WebSocket EVENT] Cleared active order tracking for {order_id}"
                    )

                    if is_test_order:
                        logger.info(
                            f"[NO-FILL-TEST] [WebSocket EVENT] Test order {order_id} completed with status: {order_status}"
                        )

            # Log trade if order is filled
            if order_status == "filled" and self.db_handler:
                trade_record = {
                    "timestamp": datetime.now(),
                    "symbol": self.trading_state.symbol,
                    "side": "BUY" if filled_qty > 0 else "SELL",
                    "quantity": abs(filled_qty),
                    "price": filled_price,
                    "order_id": order_id,
                }
                await self.db_handler.log_trade_record(trade_record)
                logger.info(f"[WebSocket EVENT] Trade record logged: {trade_record}")

                if is_test_order:
                    logger.warning(
                        f"[NO-FILL-TEST] [WebSocket EVENT] UNEXPECTED: Test order {order_id} was filled! This should not happen."
                    )

            # Update position tracking
            if filled_qty != 0:
                old_position = self.trading_state.current_position_qty
                self.trading_state.update_position(
                    self.trading_state.current_position_qty + filled_qty
                )
                logger.info(
                    f"[WebSocket EVENT] Position updated: {old_position} -> {self.trading_state.current_position_qty} (change: {filled_qty})"
                )

                if is_test_order:
                    logger.warning(
                        f"[NO-FILL-TEST] [WebSocket EVENT] UNEXPECTED: Test order caused position change! Old: {old_position}, New: {self.trading_state.current_position_qty}"
                    )

        except Exception as e:
            logger.error(f"[WebSocket EVENT] Error in handle_trade_update: {e}")
            self.exception_handler.handle_exception(
                e, ErrorCategory.ORDER_EXECUTION, ErrorSeverity.HIGH
            )

    async def handle_trade(self, trade_data):
        """
        Handle trade data from broker stream
        """
        logger.debug(
            f"Trade Received: {trade_data.symbol} Price={trade_data.price} Qty={trade_data.size}"
        )
        if trade_data.symbol == self.trading_state.symbol:
            self.trading_state.update_last_price(trade_data.price, "trade")
            await self.data_queue.put(
                {
                    "type": "trade",
                    "symbol": trade_data.symbol,
                    "price": trade_data.price,
                    "size": trade_data.size,
                    "timestamp": trade_data.timestamp,
                }
            )

    async def handle_bar(self, bar_data):
        """
        Handle bar data from broker stream
        """
        logger.debug(
            f"Bar Received: {bar_data.symbol} O={bar_data.open} H={bar_data.high} L={bar_data.low} C={bar_data.close} V={bar_data.volume}"
        )
        if bar_data.symbol == self.trading_state.symbol:
            self.trading_state.update_last_price(bar_data.close, "bar")
            await self.data_queue.put(
                {
                    "type": "bar",
                    "symbol": bar_data.symbol,
                    "open": bar_data.open,
                    "high": bar_data.high,
                    "low": bar_data.low,
                    "close": bar_data.close,
                    "volume": bar_data.volume,
                    "timestamp": bar_data.timestamp,
                }
            )

    def _risk_check(self, signal_record: dict) -> bool:
        """
        Execute risk check
        """
        try:
            symbol = signal_record["symbol"]
            price = signal_record.get("price", 0)

            if price <= 0:
                logger.warning(f"Invalid price for {symbol}: {price}")
                return False

            # Simplified concentration check
            current_positions = self.trading_state.get_positions()
            total_position_value = sum(
                abs(qty) * price for qty in current_positions.values()
            )
            portfolio_value = self.trading_state.get_portfolio_value()

            if portfolio_value > 0:
                concentration = total_position_value / portfolio_value
                max_concentration = (
                    self.app_config.get("live_trading", {})
                    .get("risk_limits", {})
                    .get("max_concentration", 0.8)
                )
                if concentration > max_concentration:
                    logger.warning(f"Concentration risk too high: {concentration:.2%}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Risk check failed: {e}")
            return False

    @handle_exceptions(ErrorCategory.ORDER_EXECUTION, ErrorSeverity.HIGH)
    def _execute_trade(self, signal: str, current_price: float):
        """Execute a trading signal through the safe execution pipeline.

        Pipeline: Signal → SignalTarget → OrderPlan → BrokerAdapter.

        This replaces the previous ad-hoc order-param building with a
        standardised three-stage pipeline that is easier to audit and
        extend to multi-broker / multi-market scenarios.
        """
        no_fill_config = self.app_config.get("live_trading", {}).get(
            "no_fill_test_mode", {}
        )
        is_test_mode = no_fill_config.get("enabled", False)

        baseline_cash = self.trading_state.last_known_cash
        baseline_position = self.trading_state.current_position_qty

        # --- Stage 0: QEE backend (existing, unchanged) ---
        if self.qee_backend is not None:
            live_config = self.app_config.get("live_trading", {})
            strategy_name = live_config.get("strategy", "mean_reversion")
            default_qty = live_config.get("default_order_qty", 10)
            broker_cfg = live_config.get("broker", {})
            market = broker_cfg.get("market", "US")

            result = self.qee_backend.execute_signal(
                signal,
                symbol=self.trading_state.symbol,
                market=market,
                order_qty=default_qty,
                signal_price=current_price,
                strategy=strategy_name,
            )
            if result.get("error"):
                logger.error("QEE execution failed: %s", result["error"])
            elif result.get("executed"):
                logger.info(
                    "QEE execution succeeded: %s orders, run_id=%s",
                    result.get("order_count"),
                    result.get("run_id"),
                )
            else:
                logger.info(
                    "QEE dry-run planned: %s orders, run_id=%s",
                    result.get("order_count"),
                    result.get("run_id"),
                )
            return

        # --- Stage 1: Signal → SignalTarget ---
        live_trading_config = self.app_config.get("live_trading", {})
        broker_cfg = live_trading_config.get("broker", {})
        market = broker_cfg.get("market", "US")
        strategy_name = live_trading_config.get("strategy", "mean_reversion")
        default_qty = live_trading_config.get("default_order_qty", 10)

        target = signal_to_target(
            signal,
            symbol=self.trading_state.symbol,
            market=market,
            order_qty=default_qty,
            signal_price=current_price,
            current_position_qty=self.trading_state.current_position_qty,
            strategy=strategy_name,
        )

        if target is None:
            logger.debug("Signal %s mapped to no target (HOLD).", signal)
            return

        logger.info(
            "Signal→Target: %s → %s (weight=%.2f, qty=%d)",
            signal,
            target.signal,
            target.target_weight,
            target.order_qty,
        )

        # --- Stage 2: CLOSE signal special handling ---
        if target.signal == "CLOSE":
            if is_test_mode:
                logger.info(
                    "[NO-FILL-TEST] Skipping CLOSE signal for %s",
                    target.symbol,
                )
                return

            logger.info("Executing CLOSE for %s via pipeline.", target.symbol)
            try:
                self.broker_handler.api.close_position(target.symbol)
                logger.info("CLOSE submitted via broker close_position for %s.", target.symbol)
            except AttributeError:
                result = execute_close_via_order(
                    self.broker_handler,
                    target.symbol,
                    self.trading_state.current_position_qty,
                    current_price,
                )
                self._handle_execution_result(result, baseline_cash, baseline_position, current_price, is_test_mode)
            return

        # --- Stage 3: SignalTarget → OrderPlan ---
        strategy_config = self.app_config.get("strategies", {}).get(strategy_name, {})
        order_settings = strategy_config.get("order_settings", {})

        plan_opts = OrderPlanOptions(
            lot_size=broker_cfg.get("lot_size", 1),
            buy_markup_bps=order_settings.get("limit_price_offset_pct", 0.0005) * 10000,
            sell_discount_bps=order_settings.get("limit_price_offset_pct", 0.0005) * 10000,
            default_order_type=order_settings.get("entry_order_type", "market"),
        )

        plan = build_order_plan(
            target,
            current_price=current_price,
            options=plan_opts,
            is_test_mode=is_test_mode,
            test_price_offset_pct=no_fill_config.get("price_offset_pct", 0.10),
        )

        logger.info(
            "Target→Plan: %s %s %s @ %s (limit=%s, lot=%d)",
            plan.side,
            plan.qty,
            plan.symbol,
            plan.order_type,
            plan.limit_price,
            plan.lot_size,
        )

        # --- Stage 4: OrderPlan → BrokerAdapter ---
        result = execute_order_plan(plan, self.broker_handler)
        self._handle_execution_result(result, baseline_cash, baseline_position, current_price, is_test_mode)

    def _handle_execution_result(self, result, baseline_cash, baseline_position, current_price, is_test_mode):
        """Post-order tracking: set active order and schedule reconciliation."""
        order = result.get("order")
        if order is None:
            logger.error("Order execution failed: %s", result.get("error"))
            return

        order_id = getattr(order, "id", getattr(order, "order_id", None))
        if not order_id:
            logger.error("Order placed but no id returned: %s", order)
            return

        client_order_id = getattr(order, "client_order_id", "")
        plan = result.get("plan")

        if is_test_mode:
            logger.info("[NO-FILL-TEST] Order placed: %s", order_id)
            no_fill_config = self.app_config.get("live_trading", {}).get("no_fill_test_mode", {})
            test_duration = no_fill_config.get("test_duration_seconds", 60)
            asyncio.create_task(  # noqa: RUF006 — fire-and-forget, handled by auto-cancel
                self._auto_cancel_test_order(order_id, test_duration)
            )
        else:
            logger.info("Order placed: %s", order_id)

        self.trading_state.set_active_order(order_id, client_order_id)

        side = getattr(plan, "side", "buy") if plan else "buy"
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(  # noqa: RUF006 — fire-and-forget, handed to event loop
                self._post_order_reconciliation(
                    order_id,
                    baseline_cash=baseline_cash,
                    baseline_position=baseline_position,
                    side=side,
                    reference_price=current_price,
                    is_test_mode=is_test_mode,
                )
            )
        except RuntimeError:
            logger.debug(
                "Event loop not running; skipping post-order reconciliation for %s",
                order_id,
            )

    async def start_live_trading(self):
        """Start the live trading system"""
        try:
            # Initialize components
            self.initialize_components()

            # Get initial account and position state
            logger.info("Fetching initial account and position state...")
            try:
                account_info = self.broker_handler.get_account()
                if account_info:
                    self.trading_state.update_cash_and_value(
                        float(account_info.cash), float(account_info.portfolio_value)
                    )
                else:
                    logger.warning("Could not fetch initial account info.")

                position_info = self.broker_handler.get_position(
                    self.trading_state.symbol
                )
                if position_info:
                    self.trading_state.update_position(float(position_info.qty))
                else:
                    logger.info(
                        f"No initial position found for {self.trading_state.symbol}."
                    )
                    self.trading_state.update_position(0.0)

            except Exception as e:
                logger.error(f"Error fetching initial state: {e}", exc_info=True)

            # Create data queue
            self.data_queue = asyncio.Queue()

            # Start performance monitoring if db_handler is available
            if self.db_handler:
                self.performance_monitor_task = asyncio.create_task(
                    self._monitor_performance()
                )
                logger.info("Performance monitoring started")

            # Start the resilient stream and trading loop
            await self._run_stream_with_reconnect()

        except Exception as e:
            logger.error(f"Error in start_live_trading: {e}")
            raise

    async def _run_stream_with_reconnect(self):
        """Run the WebSocket stream with a resilient reconnection loop."""
        initial_delay = 1.0
        max_delay = 60.0
        delay = initial_delay

        while not self._stop_requested.is_set():
            trading_loop_task = None
            try:
                logger.info("Attempting to start data stream...")
                # Setup stream before each connection attempt
                await self.broker_handler.setup_stream(
                    symbols=[self.trading_state.symbol],
                    trade_handler_cb=self.handle_trade,
                    bar_handler_cb=self.handle_bar,
                    order_update_handler_cb=self.handle_trade_update,
                )

                # Start the trading loop concurrently with the stream
                trading_loop_task = asyncio.create_task(self.trading_loop())
                logger.info("Trading loop started.")

                # This will run until the connection is lost
                await self.broker_handler.start_streaming()

            except (
                websockets.exceptions.ConnectionClosedError,
                ConnectionRefusedError,
                ConnectionResetError,
            ) as e:
                logger.warning(
                    f"WebSocket connection lost: {e}. Reconnecting in {delay:.2f} seconds..."
                )
            except Exception as e:
                logger.error(
                    f"An unexpected error occurred in the stream handler: {e}",
                    exc_info=True,
                )
                logger.warning(f"Attempting to reconnect in {delay:.2f} seconds...")
            finally:
                if "trading_loop_task" in locals() and not trading_loop_task.done():  # type: ignore[union-attr]
                    trading_loop_task.cancel()  # type: ignore[union-attr]
                    try:
                        await trading_loop_task  # type: ignore[union-attr]
                    except asyncio.CancelledError:
                        pass
                await self.broker_handler.stop_streaming()
                if not self._stop_requested.is_set():
                    await asyncio.sleep(delay)
                    # Exponential backoff with jitter
                    delay = min(max_delay, delay * 2) + random.uniform(0, 1)
                else:
                    logger.info("Stop requested, not reconnecting.")

    async def trading_loop(self):
        """The main trading loop to process data and execute trades."""
        ACCOUNT_REFRESH_INTERVAL = 300
        last_account_refresh_time = asyncio.get_event_loop().time()

        while not self._stop_requested.is_set():
            try:
                current_time = asyncio.get_event_loop().time()
                if current_time - last_account_refresh_time >= ACCOUNT_REFRESH_INTERVAL:
                    logger.info(
                        "[RECONCILE] Starting periodic account and position refresh..."
                    )
                    try:
                        # Enhanced reconciliation logging for account info
                        refreshed_account_info = self.broker_handler.get_account()
                        if refreshed_account_info:
                            if (
                                self.trading_state.last_known_cash is not None
                                and abs(
                                    float(refreshed_account_info.cash)
                                    - self.trading_state.last_known_cash
                                )
                                > 0.01
                            ):
                                logger.warning(
                                    f"[RECONCILE] Cash mismatch detected! Stream state: ${self.trading_state.last_known_cash:.2f}, REST API state: ${float(refreshed_account_info.cash):.2f}"
                                )
                                logger.info(
                                    "[RECONCILE] Trusting REST API cash value and updating internal state"
                                )
                            else:
                                logger.info(
                                    f"[RECONCILE] Cash values consistent: ${float(refreshed_account_info.cash):.2f}"
                                )

                            self.trading_state.update_cash_and_value(
                                float(refreshed_account_info.cash),
                                float(refreshed_account_info.portfolio_value),
                            )

                        # Enhanced reconciliation logging for positions
                        refreshed_position_info = self.broker_handler.get_position(
                            self.trading_state.symbol
                        )
                        refreshed_qty = 0.0
                        if refreshed_position_info:
                            refreshed_qty = float(refreshed_position_info.qty)

                        logger.info(
                            f"[RECONCILE] Position check for {self.trading_state.symbol}: Stream state: {self.trading_state.current_position_qty}, REST API state: {refreshed_qty}"
                        )

                        if (
                            abs(refreshed_qty - self.trading_state.current_position_qty)
                            > 0.01
                        ):
                            logger.warning(
                                f"[RECONCILE] Position mismatch detected! Stream state: {self.trading_state.current_position_qty}, REST API state: {refreshed_qty}"
                            )
                            logger.warning(
                                "[RECONCILE] Trusting REST API state and syncing internal position"
                            )
                            self.trading_state.update_position(refreshed_qty)
                            logger.info(
                                f"[RECONCILE] Position synchronized to REST API: {self.trading_state.symbol} -> {refreshed_qty}"
                            )
                        else:
                            logger.info(
                                f"[RECONCILE] Position values consistent for {self.trading_state.symbol}: {refreshed_qty}"
                            )

                        # Enhanced order status reconciliation
                        if self.trading_state.active_order_id:
                            logger.info(
                                f"[RECONCILE] Checking active order status: {self.trading_state.active_order_id}"
                            )

                            # Get the official state from the REST API
                            refreshed_order_info = self.broker_handler.get_order(
                                self.trading_state.active_order_id
                            )
                            rest_status = (
                                refreshed_order_info.status
                                if refreshed_order_info
                                else "not_found"
                            )

                            # Get the last known state from the WebSocket stream
                            stream_status = (
                                self.trading_state.last_known_stream_status or "unknown"
                            )

                            logger.info(
                                f"[RECONCILE] Order {self.trading_state.active_order_id} status comparison - Stream: '{stream_status}', REST API: '{rest_status}'"
                            )

                            if stream_status != rest_status:
                                logger.warning(
                                    f"[RECONCILE] Order status mismatch detected! Stream state: '{stream_status}', REST API state: '{rest_status}'"
                                )
                                logger.warning(
                                    f"[RECONCILE] Trusting REST API state: '{rest_status}'. Updating internal state."
                                )

                                # Update the stream status to match REST API
                                import time

                                self.trading_state.update_stream_order_status(
                                    self.trading_state.active_order_id,
                                    rest_status,
                                    time.time(),
                                )

                                # Handle terminal states
                                if rest_status in [
                                    "filled",
                                    "canceled",
                                    "expired",
                                    "rejected",
                                ]:
                                    logger.info(
                                        f"[RECONCILE] Order {self.trading_state.active_order_id} is in terminal state '{rest_status}', clearing active order tracking"
                                    )
                                    self.trading_state.clear_active_order()

                            else:
                                logger.info(
                                    f"[RECONCILE] Order status consistent: '{rest_status}'. No action needed."
                                )
                        else:
                            logger.debug("[RECONCILE] No active order to reconcile")

                        last_account_refresh_time = current_time
                        logger.info(
                            "[RECONCILE] Periodic reconciliation completed successfully"
                        )

                    except Exception as refresh_err:
                        logger.error(
                            f"[RECONCILE] Error during periodic reconciliation: {refresh_err}",
                            exc_info=True,
                        )

                # Process from the queue
                queued_item = await asyncio.wait_for(self.data_queue.get(), timeout=1.0)
                data_type = queued_item.get("type")
                logger.debug(
                    f"Processing item from queue: Type={data_type}, Item={queued_item}"
                )

                signal = None
                current_price = None
                if data_type in ["trade", "bar"]:
                    current_price = self.trading_state.last_trade_price
                    if not current_price:
                        current_price = queued_item.get("price")
                    if not current_price and data_type == "bar":
                        current_price = (
                            self.trading_state.last_bar_close
                            or queued_item.get("close")
                        )

                    if current_price:
                        signal = self.trading_strategy.get_signal(
                            current_price,
                            self.trading_state.current_position_qty,
                        )
                        logger.info(
                            f"Strategy generated signal: {signal} based on price {current_price:.2f} and position {self.trading_state.current_position_qty}"
                        )

                        # Record signal
                        if signal != "HOLD":
                            signal_record = {
                                "timestamp": datetime.now(),
                                "symbol": self.trading_state.symbol,
                                "signal": (
                                    1.0
                                    if signal == "BUY"
                                    else -1.0
                                    if signal == "SELL"
                                    else 0.0
                                ),
                                "price": current_price,
                                "confidence": self.trading_strategy.get_signal_confidence(),
                            }
                            self.signal_history.append(signal_record)
                    else:
                        logger.warning(
                            "No current price available (trade or bar) to generate signal."
                        )

                # Execute trades if signal generated and no active order
                if (
                    signal not in [None, "HOLD"]
                    and self.trading_state.active_order_id is None
                ):
                    logger.info(
                        f"Received signal: {signal} for {self.trading_state.symbol}"
                    )

                    # --- START OF NEW PRE-TRADE CHECKS ---
                    default_qty = self.app_config.get("live_trading", {}).get(
                        "default_order_qty", 10
                    )
                    order_qty = default_qty
                    trade_value = order_qty * current_price

                    # 1. Liquidity and Impact Check
                    avg_volume = (
                        np.mean(list(self.risk_manager.volume_history))
                        if self.risk_manager.volume_history
                        else 0
                    )
                    volatility = (
                        np.std(list(self.risk_manager.returns_history))
                        if len(self.risk_manager.returns_history) > 1
                        else 0
                    )

                    liquidity_passed, liquidity_details = (
                        self.risk_manager.check_liquidity_and_impact(
                            order_size=order_qty,
                            recent_avg_volume=avg_volume,
                            current_volatility=volatility,
                        )
                    )

                    # 2. Leverage and Exposure Check
                    portfolio_value = (
                        self.trading_state.last_known_portfolio_value
                        or self.performance_analyzer.initial_capital
                    )
                    gross_position_value = abs(
                        self.trading_state.current_position_qty * float(current_price)  # type: ignore[arg-type]
                    )

                    leverage_passed, leverage_warnings = (
                        self.risk_manager.check_leverage_and_exposure(
                            proposed_trade_value=trade_value,
                            portfolio_value=portfolio_value,
                            gross_position_value=gross_position_value,
                            cash=self.trading_state.last_known_cash,
                        )
                    )

                    # 3. Final Decision
                    if liquidity_passed and leverage_passed:
                        logger.info(
                            "All pre-trade risk checks passed. Proceeding with trade execution."
                        )
                        assert current_price is not None
                        self._execute_trade(signal, current_price)
                    else:
                        all_warnings = (
                            liquidity_details.get("warnings", []) + leverage_warnings
                        )
                        logger.warning(
                            f"Trade aborted for {self.trading_state.symbol} due to failed risk checks: {'; '.join(all_warnings)}"
                        )
                    # --- END OF NEW PRE-TRADE CHECKS ---

                elif (
                    signal not in [None, "HOLD"]
                    and self.trading_state.active_order_id is not None
                ):
                    logger.info(
                        f"Holding off on new signal {signal}, active order exists: {self.trading_state.active_order_id}"
                    )

                self.data_queue.task_done()

            except asyncio.TimeoutError:
                logger.debug(
                    "No data received from queue in the last 1 second. Continuing..."
                )
                continue
            except Exception as loop_error:
                logger.error(f"Error in main trading loop: {loop_error}", exc_info=True)
                await asyncio.sleep(5)

    async def _verify_state_once(self):
        """
        Performs a single, on-demand verification pass against the REST API
        and applies corrective action if a mismatch is found.
        This is primarily for demonstration and testing purposes.
        """
        logger.info("[VERIFY] Performing one-shot account and position refresh.")

        # 1. Refresh account info (cash, portfolio value)
        refreshed_account_info = self.broker_handler.get_account_info()  # type: ignore[union-attr]
        if refreshed_account_info:
            self.trading_state.update_cash_and_value(
                float(refreshed_account_info.cash),  # type: ignore[arg-type]
                float(refreshed_account_info.portfolio_value),  # type: ignore[arg-type]
            )

        # 2. Refresh position info and check for discrepancies
        position = self.broker_handler.get_position(self.trading_state.symbol)  # type: ignore[union-attr]
        api_qty = float(getattr(position, "qty", 0.0)) if position else 0.0

        stream_qty = self.trading_state.current_position_qty

        if abs(api_qty - stream_qty) > 0.01:
            logger.warning(
                f"[VERIFY] Position mismatch for {self.trading_state.symbol}: "
                f"Stream state is {stream_qty}, but REST API state is {api_qty}. Syncing."
            )
            self.trading_state.update_position(api_qty)
            logger.info(
                f"[VERIFY] Sync complete. Position for {self.trading_state.symbol} is now {api_qty}."
            )
        else:
            logger.info(
                f"[VERIFY] State consistent for {self.trading_state.symbol}: "
                f"Stream and REST API both show position of {api_qty}."
            )

        logger.info("[VERIFY] Verification pass complete.")

    async def stop_trading(self):
        """Stop the trading system"""
        logger.info("Stopping trading system...")
        self._stop_requested.set()

        try:
            # Cancel performance monitoring task if it exists
            if (
                self.performance_monitor_task
                and not self.performance_monitor_task.done()
            ):
                self.performance_monitor_task.cancel()
                try:
                    await self.performance_monitor_task
                except asyncio.CancelledError:
                    pass
                self.performance_monitor_task = None
                logger.info("Performance monitoring stopped")

            # Close broker connection
            if self.broker_handler:
                await self.broker_handler.stop_streaming()  # Ensure stream is stopped
                # The close() method for REST session should be implemented in broker_handler if needed
                # await self.broker_handler.close()

            # Clear data queue
            if self.data_queue:
                while not self.data_queue.empty():
                    try:
                        self.data_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                logger.info("Data queue cleared")

            # Generate final performance summary
            final_report = (
                self.performance_analyzer.generate_performance_report()
                if hasattr(self.performance_analyzer, "generate_performance_report")
                else {}
            )

            # Export reports
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            paths_config = self.app_config.get("paths", {})
            charts_dir = paths_config.get("chart_dir", "output/charts")
            logs_dir = paths_config.get("log_dir", "output/logs")

            os.makedirs(charts_dir, exist_ok=True)
            os.makedirs(logs_dir, exist_ok=True)

            self.performance_analyzer.plot_performance_charts(
                os.path.join(charts_dir, f"live_trading_performance_{timestamp}.png")
            )

            self.exception_handler.export_error_log(
                os.path.join(logs_dir, f"live_trading_errors_{timestamp}.json")
            )

            logger.info("Trading system stopped successfully")
            return final_report

        except Exception as e:
            logger.error(f"Error occurred while stopping trading system: {e}")
            return {"error": str(e)}


if __name__ == "__main__":
    from intraday_trader.live.session import main as _main

    _main()

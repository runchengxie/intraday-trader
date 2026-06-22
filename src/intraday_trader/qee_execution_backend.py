"""QEE execution backend for intraday-trader live trading.

Routes signals through quant-execution-engine instead of submitting orders
directly to the broker.  Imports are lazy so the module is importable even
when ``quant_execution_engine`` is not installed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .qee_target_exporter import TargetExportError, signal_to_targets

logger = logging.getLogger(__name__)


class QEEExecutionBackend:
    """Wraps :class:`quant_execution_engine.facade.QEEFacade` for intraday use.

    When the execution backend is ``"qee"``, :meth:`EnhancedTradingSystem._execute_trade`
    routes through this backend instead of calling ``BrokerAPIHandler.place_order``
    directly.

    Config keys (under ``live_trading.execution.qee``):
        broker_name (str):
            QEE broker backend name. Default ``"alpaca-paper"``.
        dry_run (bool):
            If True, plan rebalance without submitting orders. Default True.
        target_output_dir (str):
            Directory for exported targets.json lineage files.
            Default ``"outputs/targets"``.
        allow_short (bool):
            If True, SELL from flat position is treated as short entry.
            NOT SUPPORTED by QEE yet. Default False.
        order_qty (int):
            Default order quantity for BUY signals. Default 10.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.broker_name = str(cfg.get("broker_name", "alpaca-paper"))
        self.dry_run = bool(cfg.get("dry_run", True))
        self.target_output_dir = str(
            cfg.get("target_output_dir", "outputs/targets")
        )
        self.allow_short = bool(cfg.get("allow_short", False))
        self.default_order_qty = int(cfg.get("order_qty", 10))
        self._facade: Any = None

        if self.dry_run:
            logger.info(
                "QEE execution backend initialized: broker=%s, dry_run=True "
                "(orders will be PLANNED but NOT submitted)",
                self.broker_name,
            )
        else:
            logger.warning(
                "QEE execution backend initialized: broker=%s, dry_run=False "
                "(ORDERS WILL BE SUBMITTED)",
                self.broker_name,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_signal(
        self,
        signal: str,
        *,
        symbol: str,
        market: str = "US",
        order_qty: int | None = None,
        signal_price: float | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        """Convert a signal to targets, then execute through QEE.

        Returns a summary dict with keys:
            executed (bool), error (str|None), order_count (int),
            run_id (str), audit_log_path (str).
        """
        # 1. Convert signal → targets
        try:
            targets = signal_to_targets(
                signal,
                symbol=symbol,
                market=market,
                order_qty=order_qty or self.default_order_qty,
                signal_price=signal_price,
                strategy=strategy,
                allow_short=self.allow_short,
            )
        except TargetExportError as exc:
            logger.error("Signal → target conversion failed: %s", exc)
            return {"executed": False, "error": str(exc), "order_count": 0}

        if not targets:
            logger.debug("No targets generated for signal %s (HOLD or blocked).", signal)
            return {"executed": False, "error": None, "order_count": 0}

        # 2. Optionally export lineage
        asof = datetime.now(timezone.utc).isoformat()
        audit_path = ""
        try:
            from pathlib import Path

            from .qee_target_exporter import export_targets_json

            target_dir = Path(self.target_output_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            out_path = target_dir / f"{symbol}_{signal}_{ts}_targets.json"
            audit_path = export_targets_json(
                targets, str(out_path), source="intraday-trader", asof=asof
            )
            logger.info("Targets exported to %s", audit_path)
        except Exception:
            logger.debug("Targets.json export skipped", exc_info=True)

        # 3. Execute through QEE facade
        try:
            facade = self._get_facade()
            result = facade.execute(
                targets,
                dry_run=self.dry_run,
                target_source="intraday-trader",
                target_asof=asof,
            )
        except Exception as exc:
            logger.error("QEE facade execution failed: %s", exc)
            return {"executed": False, "error": str(exc), "order_count": 0}

        # 4. Log and return summary
        if result.error:
            logger.error("QEE execution error: %s", result.error)
        elif result.dry_run:
            logger.info(
                "QEE dry-run complete: %d orders planned, run_id=%s",
                result.order_count,
                result.run_id,
            )
        else:
            logger.info(
                "QEE execution complete: %d orders submitted, run_id=%s",
                result.order_count,
                result.run_id,
            )

        return {
            "executed": result.executed,
            "error": result.error,
            "order_count": result.order_count,
            "run_id": result.run_id,
            "audit_log_path": result.audit_log_path or audit_path,
        }

    def get_account_snapshot(self) -> dict[str, Any]:
        """Return current account state from QEE's broker adapter."""
        try:
            return self._get_facade().get_account_snapshot()
        except Exception as exc:
            logger.error("Failed to get account snapshot: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_facade(self) -> Any:
        """Lazy-load and cache the QEE facade."""
        if self._facade is None:
            from quant_execution_engine.facade import QEEFacade

            self._facade = QEEFacade(broker_name=self.broker_name)
            logger.debug("QEEFacade initialized for broker=%s", self.broker_name)
        return self._facade

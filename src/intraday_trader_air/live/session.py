"""Live trading session runner — event-loop wiring and signal handling.

Extracted from ``scripts/run_live_trading.py`` to reduce the size of
the main trading module and separate orchestration concerns.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import asdict
from pathlib import Path

from intraday_trader_air.configuration import load_app_config

logger = logging.getLogger(__name__)


# ── signal handling ──────────────────────────────────────────────────────


async def _shutdown(sig, loop):
    """Cancel all outstanding tasks on SIGINT / SIGTERM."""
    signal_name = sig
    if isinstance(sig, int):
        try:
            signal_name = signal.Signals(sig).name
        except ValueError:
            signal_name = f"Signal {sig}"
    elif hasattr(sig, "name"):
        signal_name = sig.name

    logger.info("Received exit signal %s...", signal_name)

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    if tasks:
        logger.info("Cancelling %d outstanding tasks...", len(tasks))
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("All outstanding tasks have been processed.")
    else:
        logger.info("No other outstanding tasks to cancel.")


# ── session runner ────────────────────────────────────────────────────────


async def run_trading_session(app_config: dict) -> None:
    """Core async logic for a single live trading session."""
    from intraday_trader_air.scripts.run_live_trading import EnhancedTradingSystem

    trading_system = EnhancedTradingSystem(app_config)

    try:
        await trading_system.start_live_trading()
    except Exception as e:
        logger.error("Trading system runtime error: %s", e)
        await trading_system.stop_trading()


# ── CLI entry point ───────────────────────────────────────────────────────


def main() -> None:
    """Main entry point — load config, wire signals, run event loop."""
    # 1. Load configuration via project-standard loader
    app_config_raw = load_app_config(Path("config.yml"))
    app_config = asdict(app_config_raw)

    # 2. Set up logging from loaded config
    log_config = app_config.get("logging", {})
    log_level = log_config.get("level", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format=log_config.get(
            "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ),
        datefmt=log_config.get("datefmt", "%Y-%m-%d %H:%M:%S"),
    )

    # 3. Re-obtain logger (now that logging is configured)
    global logger
    logger = logging.getLogger(__name__)

    loop = asyncio.get_event_loop()

    try:
        for sig_val in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig_val,
                lambda s=sig_val: asyncio.create_task(_shutdown(s, loop)),
            )
    except NotImplementedError:
        logger.info(
            "loop.add_signal_handler not implemented, falling back to "
            "signal.signal (Windows)."
        )
        signal.signal(
            signal.SIGINT, lambda s, f: asyncio.create_task(_shutdown(s, loop))
        )
        signal.signal(
            signal.SIGTERM, lambda s, f: asyncio.create_task(_shutdown(s, loop))
        )

    try:
        loop.run_until_complete(run_trading_session(app_config))
    except asyncio.CancelledError:
        logger.info("Main task was cancelled.")
    finally:
        logger.info("Cleaning up event loop resources...")
        pending = asyncio.all_tasks(loop=loop)
        if pending:
            logger.info(
                "Waiting for %d pending tasks to complete before closing loop...",
                len(pending),
            )
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        logger.info("Event loop closed.")
        loop.close()

"""Broker adapter factory.

Creates the right :class:`~intraday_trader.brokers.protocols.BrokerAdapter`
based on the ``live_trading.broker`` section of ``config.yml``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_broker(app_config: dict[str, Any]) -> Any:
    """Instantiate the broker adapter configured in *app_config*.

    Config shape (under ``live_trading.broker``):

    .. code-block:: yaml

        live_trading:
          broker:
            name: "alpaca"       # "alpaca" | "futu"
            market: "HK"         # for Futu: "HK" | "US" | "CN"
            mode: "simulate"     # for Futu: "simulate" | "real"
            host: "127.0.0.1"    # for Futu: OpenD host
            port: 11111           # for Futu: OpenD port

    When no ``broker`` section is present, falls back to Alpaca for
    backward compatibility.
    """
    broker_cfg = app_config.get("live_trading", {}).get("broker", {})
    if not broker_cfg:
        logger.info("No broker config found, defaulting to Alpaca.")
        return _create_alpaca()

    name = str(broker_cfg.get("name", "alpaca")).strip().lower()

    if name == "alpaca":
        return _create_alpaca()

    if name == "futu":
        return _create_futu(broker_cfg)

    raise ValueError(f"Unknown broker name: {name!r}. Supported: alpaca, futu.")


def _create_alpaca() -> Any:
    from .alpaca import AlpacaBrokerAdapter

    logger.info("Creating AlpacaBrokerAdapter.")
    return AlpacaBrokerAdapter()


def _create_futu(cfg: dict[str, Any]) -> Any:
    from .futu import FutuBrokerAdapter

    host = cfg.get("host")
    port = cfg.get("port")
    trd_env = cfg.get("mode")
    market = cfg.get("market", "HK")

    logger.info(
        "Creating FutuBrokerAdapter (host=%s, port=%s, env=%s, market=%s).",
        host or "127.0.0.1",
        port or 11111,
        trd_env or "SIMULATE",
        market,
    )
    return FutuBrokerAdapter(host=host, port=port, trd_env=trd_env, market=market)

"""Market data provider factory.

Creates the right :class:`~intraday_trader.data_providers.protocols.MarketDataProvider`
based on the ``data`` section of ``config.yml``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_data_provider(app_config: dict[str, Any]) -> Any:
    """Instantiate the market data provider configured in *app_config*.

    Config shape (under ``data.provider``):

    .. code-block:: yaml

        data:
          provider:
            name: "alpaca"       # "alpaca" | "futu"
            market: "HK"         # for Futu: "HK" | "US" | "CN"
            host: "127.0.0.1"    # for Futu: OpenD host
            port: 11111          # for Futu: OpenD port

    When no ``provider`` section is present, falls back to Alpaca for
    backward compatibility.
    """
    data_cfg = app_config.get("data", {})
    provider_cfg = data_cfg.get("provider", {})

    if not provider_cfg:
        logger.info("No data provider config found, defaulting to Alpaca.")
        return _create_alpaca()

    name = str(provider_cfg.get("name", "alpaca")).strip().lower()

    if name == "alpaca":
        return _create_alpaca()

    if name == "futu":
        return _create_futu(provider_cfg)

    raise ValueError(f"Unknown data provider: {name!r}. Supported: alpaca, futu.")


def _create_alpaca() -> Any:
    from .alpaca import AlpacaMarketDataProvider

    logger.info("Creating AlpacaMarketDataProvider.")
    return AlpacaMarketDataProvider()


def _create_futu(cfg: dict[str, Any]) -> Any:
    from .futu import FutuMarketDataProvider

    host = cfg.get("host")
    port = cfg.get("port")
    market = cfg.get("market", "HK")

    logger.info(
        "Creating FutuMarketDataProvider (host=%s, port=%s, market=%s).",
        host or "127.0.0.1",
        port or 11111,
        market,
    )
    return FutuMarketDataProvider(host=host, port=port, market=market)

import asyncio

# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
from unittest.mock import MagicMock

import pytest

pytest.importorskip("pytest_asyncio")
pytest.importorskip("alpaca_trade_api")
pytest.importorskip("websockets")

from intraday_trader_air.live_components import TradingState
from intraday_trader_air.scripts.run_live_trading import EnhancedTradingSystem


@pytest.mark.asyncio
async def test_trading_loop_processes_trade_and_generates_signal(mocker):
    """Ensure the trading loop consumes queue items and routes signals to execution."""
    config = {
        "live_trading": {"symbol": "AAPL"},
        "strategies": {"mean_reversion": {"params": {}}},
    }
    system = EnhancedTradingSystem(config)
    system.data_queue = asyncio.Queue()

    mock_strategy = MagicMock()
    mock_strategy.get_signal.return_value = "BUY"
    system.trading_strategy = mock_strategy

    system.trading_state = TradingState(symbol="AAPL")
    mocker.patch.object(system, "_execute_trade")

    await system.data_queue.put({"type": "trade", "price": 150.0})

    try:
        await asyncio.wait_for(system.trading_loop(), timeout=0.1)
    except asyncio.TimeoutError:
        pass  # Expected timeout after processing the item

    system.trading_strategy.get_signal.assert_called_once_with(150.0, 0.0)
    system._execute_trade.assert_called_once_with("BUY", 150.0)

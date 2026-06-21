1|import asyncio
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|from unittest.mock import MagicMock
3|
4|import pytest
5|
6|pytest.importorskip("pytest_asyncio")
7|pytest.importorskip("alpaca_trade_api")
8|pytest.importorskip("websockets")
9|
10|from intraday_trader_air.live_components import TradingState
11|from intraday_trader_air.scripts.run_live_trading import EnhancedTradingSystem
12|
13|
14|@pytest.mark.asyncio
15|async def test_trading_loop_processes_trade_and_generates_signal(mocker):
16|    """Ensure the trading loop consumes queue items and routes signals to execution."""
17|    config = {
18|        "live_trading": {"symbol": "AAPL"},
19|        "strategies": {"mean_reversion": {"params": {}}},
20|    }
21|    system = EnhancedTradingSystem(config)
22|    system.data_queue = asyncio.Queue()
23|
24|    mock_strategy = MagicMock()
25|    mock_strategy.get_signal.return_value = "BUY"
26|    system.trading_strategy = mock_strategy
27|
28|    system.trading_state = TradingState(symbol="AAPL")
29|    mocker.patch.object(system, "_execute_trade")
30|
31|    await system.data_queue.put({"type": "trade", "price": 150.0})
32|
33|    try:
34|        await asyncio.wait_for(system.trading_loop(), timeout=0.1)
35|    except asyncio.TimeoutError:
36|        pass  # Expected timeout after processing the item
37|
38|    system.trading_strategy.get_signal.assert_called_once_with(150.0, 0.0)
39|    system._execute_trade.assert_called_once_with("BUY", 150.0)
40|


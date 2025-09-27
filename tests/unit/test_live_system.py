import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from patf_trading_framework.scripts.run_live_trading import EnhancedTradingSystem
from patf_trading_framework.live_components import TradingState

@pytest.mark.asyncio
async def test_trading_loop_processes_trade_and_generates_signal(mocker):
    """
    Verify that when a trade is put on the queue, the trading_loop
    processes it and calls the strategy's get_signal method.
    """
    # Arrange
    config = {"live_trading": {"symbol": "AAPL"}, "strategies": {"mean_reversion": {"params": {}}}}
    system = EnhancedTradingSystem(config)
    system.data_queue = asyncio.Queue()

    # Mock the strategy to control its return value
    mock_strategy = MagicMock()
    mock_strategy.get_signal.return_value = "BUY"
    system.trading_strategy = mock_strategy
    
    # Mock the state and trade execution
    system.trading_state = TradingState(symbol="AAPL")
    mocker.patch.object(system, '_execute_trade')

    # Put a mock trade onto the queue
    mock_trade_data = {"type": "trade", "price": 150.0}
    await system.data_queue.put(mock_trade_data)
    
    # Act: Run the trading_loop for one iteration
    # We use asyncio.wait_for to run the loop briefly and then time it out
    # to check the state after one item is processed.
    try:
        await asyncio.wait_for(system.trading_loop(), timeout=0.1)
    except asyncio.TimeoutError:
        pass # Expected timeout after processing the item

    # Assert
    # Was the strategy's signal method called with the correct price?
    system.trading_strategy.get_signal.assert_called_once_with(150.0, 0.0)
    # Was the trade execution method called with the resulting signal?
    system._execute_trade.assert_called_once_with("BUY", 150.0)
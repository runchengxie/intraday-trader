import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("alpaca_trade_api")
from alpaca_trade_api.rest import APIError

from intraday_trader_air.broker_handler import BrokerAPIHandler


@pytest.fixture
def mock_broker_dependencies(monkeypatch, mocker):
    """Provide environment variables and stubbed Alpaca REST client for tests."""
    monkeypatch.setenv("APCA_API_KEY_ID", "test-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    mock_rest = mocker.MagicMock()
    mock_rest.get_account.return_value = mocker.MagicMock(
        id="acct-123", status="ACTIVE", buying_power="100000"
    )
    mocker.patch("intraday_trader_air.broker_handler.REST", return_value=mock_rest)

    return mock_rest


def test_place_order_api_error_handling(mock_broker_dependencies):
    """Verify that place_order returns None and logs an API error gracefully."""
    mock_rest = mock_broker_dependencies
    mock_rest.submit_order.side_effect = APIError({"code": 403, "message": "forbidden"})

    handler = BrokerAPIHandler()

    result = handler.place_order(symbol="FAIL", qty=1, side="buy", order_type="market")

    assert result is None
    mock_rest.submit_order.assert_called_once_with(
        symbol="FAIL", qty=1.0, side="buy", type="market", time_in_force="day"
    )


class _DummyStream:
    def __init__(self, *_, **__):
        self.subscribed_trades = ()
        self.subscribed_quotes = ()
        self.subscribed_bars = ()
        self.trade_updates_handler = None
        self._trade_handler = None
        self.stop_called = False

    def subscribe_trades(self, handler, *symbols):
        self._trade_handler = handler
        self.subscribed_trades = symbols

    def subscribe_quotes(self, handler, *symbols):  # pragma: no cover - unused in test
        self.subscribed_quotes = symbols

    def subscribe_bars(self, handler, *symbols):  # pragma: no cover - unused in test
        self.subscribed_bars = symbols

    def subscribe_trade_updates(self, handler):  # pragma: no cover - unused in test
        self.trade_updates_handler = handler

    async def _run_forever(self):
        await asyncio.sleep(0)
        if self._trade_handler:
            await self._trade_handler(
                SimpleNamespace(symbol="AAPL", price=123.45, size=1)
            )

    async def stop_ws(self):
        self.stop_called = True
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_streaming_uses_callbacks(monkeypatch, mock_broker_dependencies):
    """BrokerAPIHandler should forward streamed trades to the provided callback."""

    monkeypatch.setattr(
        "intraday_trader_air.broker_handler.Stream", _DummyStream
    )

    handler = BrokerAPIHandler()

    received = asyncio.Queue()

    async def trade_cb(message):
        await received.put(message)

    await handler.setup_stream(
        symbols=["AAPL"],
        trade_handler_cb=trade_cb,
        subscribe_trades=True,
        subscribe_updates=False,
    )

    dummy_stream = handler.stream
    assert isinstance(dummy_stream, _DummyStream)
    assert dummy_stream.subscribed_trades == ("AAPL",)

    stream_task = asyncio.create_task(handler.start_streaming())

    message = await asyncio.wait_for(received.get(), timeout=1)
    assert message.symbol == "AAPL"
    assert message.price == pytest.approx(123.45)

    await handler.stop_streaming()
    assert dummy_stream.stop_called is True
    await asyncio.wait_for(stream_task, timeout=1)
    assert handler.stream is None

1|import asyncio
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|from types import SimpleNamespace
3|
4|import pytest
5|
6|pytest.importorskip("alpaca_trade_api")
7|from alpaca_trade_api.rest import APIError
8|
9|from intraday_trader_air.broker_handler import BrokerAPIHandler
10|
11|
12|@pytest.fixture
13|def mock_broker_dependencies(monkeypatch, mocker):
14|    """Provide environment variables and stubbed Alpaca REST client for tests."""
15|    monkeypatch.setenv("APCA_API_KEY_ID", "test-key")
16|    monkeypatch.setenv("APCA_API_SECRET_KEY", "test-secret")
17|    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
18|
19|    mock_rest = mocker.MagicMock()
20|    mock_rest.get_account.return_value = mocker.MagicMock(
21|        id="acct-123", status="ACTIVE", buying_power="100000"
22|    )
23|    mocker.patch("intraday_trader_air.broker_handler.REST", return_value=mock_rest)
24|
25|    return mock_rest
26|
27|
28|def test_place_order_api_error_handling(mock_broker_dependencies):
29|    """Verify that place_order returns None and logs an API error gracefully."""
30|    mock_rest = mock_broker_dependencies
31|    mock_rest.submit_order.side_effect = APIError({"code": 403, "message": "forbidden"})
32|
33|    handler = BrokerAPIHandler()
34|
35|    result = handler.place_order(symbol="FAIL", qty=1, side="buy", order_type="market")
36|
37|    assert result is None
38|    mock_rest.submit_order.assert_called_once_with(
39|        symbol="FAIL", qty=1.0, side="buy", type="market", time_in_force="day"
40|    )
41|
42|
43|class _DummyStream:
44|    def __init__(self, *_, **__):
45|        self.subscribed_trades = ()
46|        self.subscribed_quotes = ()
47|        self.subscribed_bars = ()
48|        self.trade_updates_handler = None
49|        self._trade_handler = None
50|        self.stop_called = False
51|
52|    def subscribe_trades(self, handler, *symbols):
53|        self._trade_handler = handler
54|        self.subscribed_trades = symbols
55|
56|    def subscribe_quotes(self, handler, *symbols):  # pragma: no cover - unused in test
57|        self.subscribed_quotes = symbols
58|
59|    def subscribe_bars(self, handler, *symbols):  # pragma: no cover - unused in test
60|        self.subscribed_bars = symbols
61|
62|    def subscribe_trade_updates(self, handler):  # pragma: no cover - unused in test
63|        self.trade_updates_handler = handler
64|
65|    async def _run_forever(self):
66|        await asyncio.sleep(0)
67|        if self._trade_handler:
68|            await self._trade_handler(
69|                SimpleNamespace(symbol="AAPL", price=123.45, size=1)
70|            )
71|
72|    async def stop_ws(self):
73|        self.stop_called = True
74|        await asyncio.sleep(0)
75|
76|
77|@pytest.mark.asyncio
78|async def test_streaming_uses_callbacks(monkeypatch, mock_broker_dependencies):
79|    """BrokerAPIHandler should forward streamed trades to the provided callback."""
80|
81|    monkeypatch.setattr("intraday_trader_air.broker_handler.Stream", _DummyStream)
82|
83|    handler = BrokerAPIHandler()
84|
85|    received = asyncio.Queue()
86|
87|    async def trade_cb(message):
88|        await received.put(message)
89|
90|    await handler.setup_stream(
91|        symbols=["AAPL"],
92|        trade_handler_cb=trade_cb,
93|        subscribe_trades=True,
94|        subscribe_updates=False,
95|    )
96|
97|    dummy_stream = handler.stream
98|    assert isinstance(dummy_stream, _DummyStream)
99|    assert dummy_stream.subscribed_trades == ("AAPL",)
100|
101|    stream_task = asyncio.create_task(handler.start_streaming())
102|
103|    message = await asyncio.wait_for(received.get(), timeout=1)
104|    assert message.symbol == "AAPL"
105|    assert message.price == pytest.approx(123.45)
106|
107|    await handler.stop_streaming()
108|    assert dummy_stream.stop_called is True
109|    await asyncio.wait_for(stream_task, timeout=1)
110|    assert handler.stream is None
111|


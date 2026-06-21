1|import asyncio
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|import logging
3|import os
4|import time
5|import uuid
6|
7|import pytest
8|
9|pytest.importorskip("pytest_asyncio")
10|pytest.importorskip("alpaca_trade_api")
11|
12|from intraday_trader_air.broker_handler import BrokerAPIHandler
13|
14|REQUIRED_ENV_VARS = ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]
15|RUN_LIVE_STREAM_TEST = os.getenv("RUN_ALPACA_STREAM_TEST", "").lower() in {
16|    "1",
17|    "true",
18|    "yes",
19|}
20|
21|pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
22|
23|missing_creds = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
24|if missing_creds:
25|    pytestmark.append(
26|        pytest.mark.skip(
27|            reason=(
28|                "Alpaca credentials missing: set {} to run broker integration tests"
29|            ).format(", ".join(missing_creds))
30|        )
31|    )
32|
33|# --- Test Logging Configuration ---
34|logging.basicConfig(
35|    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
36|)
37|logger = logging.getLogger(__name__)
38|
39|
40|# --- Pytest Fixtures ---
41|
42|
43|@pytest.fixture(scope="module")
44|def event_loop():
45|    """Create an instance of the default event loop for the whole module."""
46|    loop = asyncio.get_event_loop_policy().new_event_loop()
47|    yield loop
48|    loop.close()
49|
50|
51|@pytest.fixture(scope="module")
52|def broker_handler():
53|    """
54|    Pytest fixture: Initializes the BrokerAPIHandler once for the entire test module.
55|    Includes robust setup and teardown logic to ensure a clean testing environment.
56|    """
57|    handler = None
58|    try:
59|        # --- Setup ---
60|        logger.info("Setting up BrokerAPIHandler for integration tests...")
61|        handler = BrokerAPIHandler()
62|
63|        # --- Pre-test Cleanup ---
64|        logger.info(
65|            "Performing pre-test cleanup: Cancelling all existing open orders..."
66|        )
67|        handler.cancel_all_orders()
68|        time.sleep(3)  # Allow time for cancellations to be processed by Alpaca
69|
70|        yield handler
71|
72|    except ValueError as e:
73|        pytest.fail(
74|            f"FATAL: Failed to initialize BrokerAPIHandler. Check .env file and API keys. Error: {e}"
75|        )
76|
77|    finally:
78|        # --- Post-test Teardown ---
79|        if handler:
80|            logger.info(
81|                "Performing post-test cleanup: Cancelling all remaining open orders..."
82|            )
83|            handler.cancel_all_orders()
84|            logger.info("Broker handler teardown complete.")
85|
86|
87|# --- REST API Integration Tests ---
88|
89|
90|async def test_connection_and_account_info(broker_handler):
91|    """Tests the basic API connection by fetching account information."""
92|    logger.info("\n--- [Test Case: Get Account Info] ---")
93|    account_info = broker_handler.get_account_info()
94|
95|    assert account_info is not None, (
96|        "Failed to get account info. Check API keys and connection."
97|    )
98|    assert hasattr(account_info, "id"), "Account info is missing 'id' attribute."
99|    assert account_info.status == "ACTIVE", (
100|        f"Account status is '{account_info.status}', not 'ACTIVE'."
101|    )
102|    logger.info(
103|        f"Successfully fetched account info. Account Status: {account_info.status}"
104|    )
105|
106|
107|async def test_full_order_cycle(broker_handler):
108|    """
109|    Tests a complete, realistic order lifecycle:
110|    1. Place a limit order far from the market to ensure it remains open.
111|    2. Check the status of the open order.
112|    3. Cancel the order.
113|    4. Verify the order's final status is 'canceled'.
114|    """
115|    symbol_to_test = "SPY"
116|    logger.info(f"\n--- [Test Case: Full Order Cycle for {symbol_to_test}] ---")
117|
118|    # 1. Place a limit buy order far below the market price
119|    logger.info("[Step 1: Placing a far-from-market limit buy order]")
120|    try:
121|        last_quote = broker_handler.api.get_latest_quote(symbol_to_test)
122|        current_price = last_quote.ap  # Current ask price
123|        # Set limit price 10% below the market to avoid execution
124|        test_limit_price = round(current_price * 0.90, 2)
125|        logger.info(
126|            f"Current ask price for {symbol_to_test} is ~${current_price:.2f}. Setting limit price to ${test_limit_price}"
127|        )
128|    except Exception as e:
129|        pytest.fail(f"Could not get latest quote for {symbol_to_test}: {e}")
130|
131|    # Use a unique client_order_id for idempotency
132|    client_order_id = f"test_cycle_{uuid.uuid4()}"
133|
134|    order = broker_handler.place_order(
135|        symbol=symbol_to_test,
136|        qty=1,
137|        side="buy",
138|        order_type="limit",
139|        time_in_force="day",
140|        limit_price=test_limit_price,
141|        client_order_id=client_order_id,
142|    )
143|    assert order is not None, "Placing buy order failed."
144|    assert order.client_order_id == client_order_id
145|    logger.info(
146|        f"Buy order submitted. Order ID: {order.id}. Waiting for status update..."
147|    )
148|    await asyncio.sleep(2)
149|
150|    # 2. Check the order status
151|    logger.info(f"\n[Step 2: Checking status for order {order.id}]")
152|    order_status = broker_handler.get_order_status(order.id)
153|    assert order_status is not None, f"Failed to get status for order {order.id}."
154|    assert order_status.status in ["new", "accepted"], (
155|        f"Order status was '{order_status.status}', not 'new' or 'accepted'."
156|    )
157|    logger.info(f"Order status is correctly '{order_status.status}'.")
158|
159|    # 3. Cancel the order
160|    logger.info(f"\n[Step 3: Cancelling order {order.id}]")
161|    cancel_success = broker_handler.cancel_order(order.id)
162|    assert cancel_success, f"Failed to send cancel request for order {order.id}."
163|    logger.info("Cancel request sent. Waiting for confirmation...")
164|    await asyncio.sleep(2)
165|
166|    # 4. Verify the order is now canceled
167|    logger.info(f"\n[Step 4: Verifying final status of order {order.id}]")
168|    final_status = broker_handler.get_order_status(order.id)
169|    assert final_status is not None, f"Failed to get final status for order {order.id}."
170|    assert final_status.status == "canceled", (
171|        f"Final order status was '{final_status.status}', not 'canceled'."
172|    )
173|    logger.info("Order cycle test successful. Final status is 'canceled'.")
174|
175|
176|async def test_list_positions(broker_handler):
177|    """Tests fetching the list of all current positions in the account."""
178|    logger.info("\n--- [Test Case: List Positions] ---")
179|    positions = broker_handler.list_positions()
180|    assert positions is not None, (
181|        "list_positions() should return a list or empty list, not None."
182|    )
183|
184|    if not positions:
185|        logger.info(
186|            "No positions currently held (as expected for a clean test account)."
187|        )
188|    else:
189|        logger.info(f"Found {len(positions)} positions:")
190|        for p in positions:
191|            logger.info(f"  - {p.symbol}: Qty={p.qty}, Market Value=${p.market_value}")
192|
193|
194|# --- WebSocket Streaming Integration Test ---
195|
196|
197|async def test_websocket_stream_receives_data(broker_handler):
198|    """
199|    Tests the most complex part of the handler: the async WebSocket stream.
200|    It verifies that the handler can connect, subscribe, and receive data.
201|    """
202|    if not RUN_LIVE_STREAM_TEST:
203|        pytest.skip(
204|            "Set RUN_ALPACA_STREAM_TEST=1 to enable the live WebSocket stream integration test."
205|        )
206|    symbol_to_stream = "AAPL"
207|    logger.info(f"\n--- [Test Case: WebSocket Stream for {symbol_to_stream}] ---")
208|
209|    # Arrange: Create a queue to hold messages received from the stream
210|    received_updates = asyncio.Queue()
211|
212|    # Create a callback function that puts received data into the queue
213|    async def stream_callback(data):
214|        await received_updates.put(data)
215|
216|    # Act: Setup and run the stream for a short duration
217|    await broker_handler.setup_stream(
218|        symbols=[symbol_to_stream],
219|        trade_handler_cb=stream_callback,
220|        subscribe_trades=True,
221|        subscribe_updates=False,  # Don't need order updates for this test
222|    )
223|
224|    stream_task = asyncio.create_task(broker_handler.start_streaming())
225|    logger.info("WebSocket stream started in background task. Waiting for data...")
226|
227|    try:
228|        # Wait for a message to arrive, with a timeout.
229|        # This will raise TimeoutError if no messages are received, failing the test.
230|        first_message = await asyncio.wait_for(received_updates.get(), timeout=15)
231|        logger.info(f"Successfully received first message from stream: {first_message}")
232|    except asyncio.TimeoutError:
233|        pytest.fail(
234|            "Did not receive any messages from the WebSocket stream within the timeout period."
235|        )
236|    finally:
237|        # Teardown: Stop the stream and cancel the background task
238|        await broker_handler.stop_streaming()
239|        stream_task.cancel()
240|        try:
241|            await stream_task
242|        except asyncio.CancelledError:
243|            pass  # This is expected
244|
245|    # Assert: Check if we received at least one message
246|    assert not received_updates.empty() or "first_message" in locals()
247|    logger.info("WebSocket stream test successful.")
248|

import asyncio
import logging
import os
import time
import uuid

import pytest

pytest.importorskip("pytest_asyncio")
pytest.importorskip("alpaca_trade_api")

from intraday_trader_air.broker_handler import BrokerAPIHandler

REQUIRED_ENV_VARS = ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

missing_creds = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_creds:
    pytestmark.append(
        pytest.mark.skip(
            reason=(
                "Alpaca credentials missing: set {} to run broker integration tests"
            ).format(", ".join(missing_creds))
        )
    )

# --- Test Logging Configuration ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# --- Pytest Fixtures ---

@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for the whole module."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="module")
def broker_handler():
    """
    Pytest fixture: Initializes the BrokerAPIHandler once for the entire test module.
    Includes robust setup and teardown logic to ensure a clean testing environment.
    """
    handler = None
    try:
        # --- Setup ---
        logger.info("Setting up BrokerAPIHandler for integration tests...")
        handler = BrokerAPIHandler()

        # --- Pre-test Cleanup ---
        logger.info("Performing pre-test cleanup: Cancelling all existing open orders...")
        handler.cancel_all_orders()
        time.sleep(3) # Allow time for cancellations to be processed by Alpaca

        yield handler

    except ValueError as e:
        pytest.fail(f"FATAL: Failed to initialize BrokerAPIHandler. Check .env file and API keys. Error: {e}")

    finally:
        # --- Post-test Teardown ---
        if handler:
            logger.info("Performing post-test cleanup: Cancelling all remaining open orders...")
            handler.cancel_all_orders()
            logger.info("Broker handler teardown complete.")


# --- REST API Integration Tests ---

async def test_connection_and_account_info(broker_handler):
    """Tests the basic API connection by fetching account information."""
    logger.info("\n--- [Test Case: Get Account Info] ---")
    account_info = broker_handler.get_account_info()

    assert account_info is not None, "Failed to get account info. Check API keys and connection."
    assert hasattr(account_info, "id"), "Account info is missing 'id' attribute."
    assert account_info.status == "ACTIVE", f"Account status is '{account_info.status}', not 'ACTIVE'."
    logger.info(f"Successfully fetched account info. Account Status: {account_info.status}")


async def test_full_order_cycle(broker_handler):
    """
    Tests a complete, realistic order lifecycle:
    1. Place a limit order far from the market to ensure it remains open.
    2. Check the status of the open order.
    3. Cancel the order.
    4. Verify the order's final status is 'canceled'.
    """
    symbol_to_test = "SPY"
    logger.info(f"\n--- [Test Case: Full Order Cycle for {symbol_to_test}] ---")

    # 1. Place a limit buy order far below the market price
    logger.info("[Step 1: Placing a far-from-market limit buy order]")
    try:
        last_quote = broker_handler.api.get_latest_quote(symbol_to_test)
        current_price = last_quote.ap  # Current ask price
        # Set limit price 10% below the market to avoid execution
        test_limit_price = round(current_price * 0.90, 2)
        logger.info(f"Current ask price for {symbol_to_test} is ~${current_price:.2f}. Setting limit price to ${test_limit_price}")
    except Exception as e:
        pytest.fail(f"Could not get latest quote for {symbol_to_test}: {e}")

    # Use a unique client_order_id for idempotency
    client_order_id = f"test_cycle_{uuid.uuid4()}"

    order = broker_handler.place_order(
        symbol=symbol_to_test, qty=1, side="buy", order_type="limit",
        time_in_force="day", limit_price=test_limit_price, client_order_id=client_order_id
    )
    assert order is not None, "Placing buy order failed."
    assert order.client_order_id == client_order_id
    logger.info(f"Buy order submitted. Order ID: {order.id}. Waiting for status update...")
    await asyncio.sleep(2)

    # 2. Check the order status
    logger.info(f"\n[Step 2: Checking status for order {order.id}]")
    order_status = broker_handler.get_order_status(order.id)
    assert order_status is not None, f"Failed to get status for order {order.id}."
    assert order_status.status in ["new", "accepted"], f"Order status was '{order_status.status}', not 'new' or 'accepted'."
    logger.info(f"Order status is correctly '{order_status.status}'.")

    # 3. Cancel the order
    logger.info(f"\n[Step 3: Cancelling order {order.id}]")
    cancel_success = broker_handler.cancel_order(order.id)
    assert cancel_success, f"Failed to send cancel request for order {order.id}."
    logger.info("Cancel request sent. Waiting for confirmation...")
    await asyncio.sleep(2)

    # 4. Verify the order is now canceled
    logger.info(f"\n[Step 4: Verifying final status of order {order.id}]")
    final_status = broker_handler.get_order_status(order.id)
    assert final_status is not None, f"Failed to get final status for order {order.id}."
    assert final_status.status == "canceled", f"Final order status was '{final_status.status}', not 'canceled'."
    logger.info("Order cycle test successful. Final status is 'canceled'.")


async def test_list_positions(broker_handler):
    """Tests fetching the list of all current positions in the account."""
    logger.info("\n--- [Test Case: List Positions] ---")
    positions = broker_handler.list_positions()
    assert positions is not None, "list_positions() should return a list or empty list, not None."

    if not positions:
        logger.info("No positions currently held (as expected for a clean test account).")
    else:
        logger.info(f"Found {len(positions)} positions:")
        for p in positions:
            logger.info(f"  - {p.symbol}: Qty={p.qty}, Market Value=${p.market_value}")


# --- WebSocket Streaming Integration Test ---

async def test_websocket_stream_receives_data(broker_handler):
    """
    Tests the most complex part of the handler: the async WebSocket stream.
    It verifies that the handler can connect, subscribe, and receive data.
    """
    symbol_to_stream = "AAPL"
    logger.info(f"\n--- [Test Case: WebSocket Stream for {symbol_to_stream}] ---")

    # Arrange: Create a queue to hold messages received from the stream
    received_updates = asyncio.Queue()

    # Create a callback function that puts received data into the queue
    async def stream_callback(data):
        await received_updates.put(data)

    # Act: Setup and run the stream for a short duration
    await broker_handler.setup_stream(
        symbols=[symbol_to_stream],
        trade_handler_cb=stream_callback,
        subscribe_trades=True,
        subscribe_updates=False # Don't need order updates for this test
    )

    stream_task = asyncio.create_task(broker_handler.start_streaming())
    logger.info("WebSocket stream started in background task. Waiting for data...")

    try:
        # Wait for a message to arrive, with a timeout.
        # This will raise TimeoutError if no messages are received, failing the test.
        first_message = await asyncio.wait_for(received_updates.get(), timeout=15)
        logger.info(f"Successfully received first message from stream: {first_message}")
    except asyncio.TimeoutError:
        pytest.fail("Did not receive any messages from the WebSocket stream within the timeout period.")
    finally:
        # Teardown: Stop the stream and cancel the background task
        await broker_handler.stop_streaming()
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass # This is expected

    # Assert: Check if we received at least one message
    assert not received_updates.empty() or 'first_message' in locals()
    logger.info("WebSocket stream test successful.")

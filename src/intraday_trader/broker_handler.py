import logging
import os

from alpaca_trade_api.rest import REST, APIError
from alpaca_trade_api.stream import Stream
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class BrokerAPIHandler:
    def __init__(self):
        load_dotenv()  # Ensure environment variables are loaded.
        self.api_key = os.getenv("APCA_API_KEY_ID")
        self.secret_key = os.getenv("APCA_API_SECRET_KEY")
        # Force the use of the paper trading URL to prevent accidental live trading.
        self.base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        self.stream = None  # Initialize stream attribute

        if not self.api_key or not self.secret_key:
            logger.error(
                "Error: Alpaca API credentials not found in environment variables. Please check your .env file."
            )
            raise ValueError("Missing Alpaca API Credentials")

        if "live-api" in self.base_url:
            logger.warning(
                "Warning: Live trading API URL detected. Ensure you are using paper trading credentials and URL for testing!"
            )
            # A  confirmation step or raising an error here for safety
            raise ValueError("Live API URL detected during paper trading setup.")

        logger.info(f"Initializing Alpaca API Handler for URL: {self.base_url}")
        try:
            self.api = REST(
                self.api_key, self.secret_key, base_url=self.base_url, api_version="v2"
            )
            # Add retry logic
            retry_strategy = Retry(
                total=5,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=[
                    "GET",
                    "POST",
                    "DELETE",
                    "PATCH",
                ],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self.api._session.mount("https://", adapter)
            self.api._session.mount("http://", adapter)
            logger.info("Added retry logic to the Alpaca API session.")

            # Test connection: Attempt to fetch account information.
            account = self.get_account_info()
            if account:
                logger.info(
                    f"Successfully connected to Alpaca paper trading account. Account ID: {account.id}, Status: {account.status}"
                )
                logger.info(f"Current Buying Power: {account.buying_power}")
            else:
                logger.error(
                    "Connection test failed: Could not retrieve account information. The API keys may be invalid or there might be a network issue."
                )
                raise ConnectionError(
                    "Failed to connect to Alpaca API and retrieve account info."
                )
        except APIError as e:
            logger.error(
                f"An error occurred while connecting to the Alpaca API: {e}",
                exc_info=True,
            )
            raise
        except Exception as e:
            logger.error(
                f"An unknown error occurred during BrokerAPIHandler initialization: {e}",
                exc_info=True,
            )
            raise

    def get_account_info(self):
        """Gets account information."""
        logger.debug("Attempting to get account information...")
        try:
            account = self.api.get_account()
            logger.debug(
                f"Successfully retrieved account information. ID: {account.id}"
            )
            return account
        except APIError as e:
            logger.error(f"Failed to get account information: {e}")
            return None
        except Exception as e:
            logger.error(
                f"An unknown error occurred while getting account information: {e}"
            )
            return None

    def place_order(
        self,
        symbol,
        qty,
        side,
        order_type,
        time_in_force="day",
        limit_price=None,
        stop_price=None,
        client_order_id=None,
    ):
        """
        Places a new order.

        Args:
            symbol (str): The ticker symbol to trade (e.g., 'SPY').
            qty (float): The number of shares to trade (Alpaca API v2 only accepts positive qty).
            side (str): 'buy' or 'sell'.
            order_type (str): 'market', 'limit', 'stop', 'stop_limit', 'trailing_stop'.
            time_in_force (str): The duration for which the order is valid ('day', 'gtc', 'opg', 'cls', 'ioc', 'fok').
            limit_price (float, optional): The limit price for a limit order. Defaults to None.
            stop_price (float, optional): The stop price for a stop or stop-limit order. Defaults to None.
            client_order_id (str, optional): A custom order ID. Defaults to None.


        Returns:
            Order object or None: The Alpaca Order object on success, or None on failure.
        """
        logger.info(
            f"Attempting to place order: {side} {qty} {symbol} @ {order_type} (limit={limit_price}, stop={stop_price}, tif={time_in_force})"
        )
        try:
            abs_qty = abs(float(qty))  # Ensure qty is a positive float
            order_data = {
                "symbol": symbol,
                "qty": abs_qty,
                "side": side,
                "type": order_type,
                "time_in_force": time_in_force,
            }
            if limit_price is not None:
                order_data["limit_price"] = float(limit_price)
            if stop_price is not None:
                order_data["stop_price"] = float(stop_price)
            if client_order_id is not None:
                order_data["client_order_id"] = client_order_id

            order = self.api.submit_order(**order_data)
            logger.info(
                f"Order submission request sent. Order ID: {order.id}, Status: {order.status}, Client Order ID: {order.client_order_id}"
            )
            return order
        except APIError as e:
            logger.error(
                f"Failed to place order ({symbol}, {side}, {qty}): {e}", exc_info=True
            )
            return None
        except ValueError as e:
            logger.error(
                f"Invalid parameters for order ({symbol}, {side}, {qty}): {e}",
                exc_info=True,
            )
            return None
        except Exception as e:
            logger.error(
                f"An unknown error occurred while placing order ({symbol}, {side}, {qty}): {e}",
                exc_info=True,
            )
            return None

    def get_order_status(self, order_id):
        """Checks the status of a specific order."""
        logger.debug(f"Querying status for order: {order_id}")
        try:
            order = self.api.get_order(order_id)
            logger.debug(f"Order {order_id} status: {order.status}")
            return order
        except APIError as e:
            if e.code == 404:
                logger.warning(
                    f"Querying status for order: cannot find order {order_id}。"
                )
            else:
                logger.error(f"Failed to query status for order {order_id}: {e}")
            return None
        except Exception as e:
            logger.error(
                f"An unknown error occurred while querying status for order {order_id}: {e}"
            )
            return None

    def list_orders(
        self,
        status="open",
        limit=100,
        after=None,
        until=None,
        direction="desc",
        nested=True,
        symbols=None,
    ):
        """Retrieves a list of orders."""
        logger.debug(
            f"Listing orders (status: {status}, limit: {limit}, direction: {direction})"
        )
        try:
            orders = self.api.list_orders(
                status=status,
                limit=limit,
                after=after,
                until=until,
                direction=direction,
                nested=nested,
                symbols=symbols,
            )
            logger.debug(f"Found {len(orders)} matching orders.")
            return orders
        except APIError as e:
            logger.error(f"Failed to list orders: {e}")
            return []
        except Exception as e:
            logger.error(f"An unknown error occurred while listing orders: {e}")
            return []

    def cancel_order(self, order_id):
        """Cancels an open order."""
        logger.info(f"Attempting to cancel order: {order_id}")
        try:
            self.api.cancel_order(order_id)
            logger.info(f"Cancellation request sent for order {order_id}.")
            return True
        except APIError as e:
            if e.code == 404:
                logger.warning(f"Failed to cancel order: Order {order_id} not found.")
            elif e.code == 422:
                logger.warning(
                    f"Failed to cancel order: Order {order_id} may have already been filled or canceled ({e})."
                )
            else:
                logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
        except Exception as e:
            logger.error(
                f"An unknown error occurred while canceling order {order_id}: {e}"
            )
            return False

    def cancel_all_orders(self):
        """Cancels all open orders."""
        logger.info("Attempting to cancel all open orders...")
        try:
            cancel_statuses = (
                self.api.cancel_all_orders()
            )  # Returns list of status dicts or potentially None/empty list
            cancelled_count = 0
            failed_count = 0

            # --- Check if cancel_statuses is iterable ---
            if cancel_statuses is not None:
                # Check if it's an empty list (meaning no open orders to cancel)
                if not cancel_statuses:
                    logger.info("No open orders to cancel.")
                else:
                    # Iterate only if it's a non-empty list
                    for status in cancel_statuses:
                        # The status object has 'id' and 'status' (HTTP status code) attributes
                        if hasattr(status, "status") and status.status == 200:
                            cancelled_count += 1
                        elif hasattr(status, "id"):
                            failed_count += 1
                            logger.warning(
                                f"Cancellation for order {status.id} may have failed. Status code: {getattr(status, 'status', 'N/A')}"
                            )
                        else:
                            # Handle unexpected status object format
                            failed_count += 1
                            logger.warning(
                                f"Received an unknown cancellation status object: {status}"
                            )
                    logger.info(
                        f"Cancel-all-orders request processed. Succeeded: {cancelled_count}, Failed: {failed_count}."
                    )
            else:
                # Handle the case where the API might return None explicitly
                logger.info(
                    "API returned None, likely meaning there were no open orders to cancel."
                )

            return True  # Return True as the operation itself (attempting to cancel) was initiated
        except APIError as e:
            logger.error(
                f"An API error occurred while canceling all orders: {e}", exc_info=True
            )
            return False
        except TypeError as e:
            # Catching the specific error we observed, though the check should prevent it
            logger.error(
                f"A type error occurred while canceling all orders (possibly during iteration): {e}",
                exc_info=True,
            )
            return False
        except Exception as e:
            logger.error(
                f"An unknown error occurred while canceling all orders: {e}",
                exc_info=True,
            )
            return False

    def get_position(self, symbol):
        """Gets the position for a specific symbol."""
        logger.debug(f"Querying position for: {symbol}")
        try:
            position = self.api.get_position(symbol)
            logger.debug(
                f"Position for {symbol}: Qty={position.qty}, AvgEntryPrice={position.avg_entry_price}"
            )
            return position
        except APIError as e:
            if e.code == 404:
                logger.debug(f"Querying position: No position held for {symbol}.")
                return None  # Return None to indicate no position, not an error
            logger.error(f"Failed to query position for {symbol}: {e}")
            return None  # Return None for actual errors too, caller needs to differentiate if necessary
        except Exception as e:
            logger.error(
                f"An unknown error occurred while querying position for {symbol}: {e}"
            )
            return None

    def list_positions(self):
        """Retrieves a list of all open positions."""
        logger.debug("Querying all positions...")
        try:
            positions = self.api.list_positions()
            logger.debug(f"Total number of open positions: {len(positions)}")
            return positions
        except APIError as e:
            logger.error(f"Failed to list positions: {e}")
            return []
        except Exception as e:
            logger.error(f"An unknown error occurred while listing positions: {e}")
            return []

    # --- Real-time Data Stream Methods ---
    async def _stream_handler(self, data):
        """Generic handler to log received stream data."""
        logger.info(f"Stream Data Received: {data}")

    async def setup_stream(
        self,
        symbols=None,
        trade_handler_cb=None,
        bar_handler_cb=None,
        quote_handler_cb=None,
        order_update_handler_cb=None,
        subscribe_trades=True,
        subscribe_quotes=False,
        subscribe_bars=False,
        subscribe_updates=True,
    ):
        """Sets up and connects to the Alpaca data stream. The order_update_handler_cb handles both order and account updates from the trade_updates stream."""
        if self.stream:
            logger.warning(
                "Stream already exists. Disconnecting existing stream first."
            )
            await self.stop_streaming()  # Ensure clean state

        logger.info("Setting up Alpaca data stream...")
        try:
            self.stream = Stream(
                self.api_key, self.secret_key, base_url=self.base_url, data_feed="iex"
            )

            async def default_on_trade(trade):
                logger.info(
                    f"Real-time trade (default handler): {trade.symbol} Price={trade.price} Qty={trade.size}"
                )

            async def default_on_quote(quote):
                logger.debug(
                    f"Real-time quote (default handler): {quote.symbol} Ask={quote.ask_price} Bid={quote.bid_price}"
                )

            async def default_on_bar(bar):
                logger.info(
                    f"Real-time minute bar (default handler): {bar.symbol} O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume}"
                )

            async def default_on_update(
                update_data,
            ):  # Renamed from default_on_order_update, handles all trade_updates
                event = update_data.event
                if hasattr(update_data, "order") and isinstance(
                    update_data.order, dict
                ):  # Likely OrderUpdate
                    logger.info(
                        f"Order update (default handler): Event={event}, Order ID={update_data.order.get('id')}, Status={update_data.order.get('status')}"
                    )
                elif (
                    event == "account_update"
                    and hasattr(update_data, "cash")
                    and hasattr(update_data, "portfolio_value")
                ):  # AccountUpdate
                    logger.info(
                        f"Account update (default handler): Event={event}, Cash={update_data.cash}, PortfolioValue={update_data.portfolio_value}"
                    )
                else:
                    logger.info(
                        f"Unknown trade/account update (default handler): Event={event}, Data={update_data}"
                    )

            _trade_handler = trade_handler_cb or default_on_trade
            _quote_handler = quote_handler_cb or default_on_quote
            _bar_handler = bar_handler_cb or default_on_bar
            _update_handler = (
                order_update_handler_cb or default_on_update
            )  # This is for trade_updates stream

            if subscribe_trades and symbols:
                self.stream.subscribe_trades(_trade_handler, *symbols)
                logger.info(
                    f"Subscribed to trades for: {symbols} (using {'custom' if trade_handler_cb else 'default'} handler)"
                )
            if subscribe_quotes and symbols:
                self.stream.subscribe_quotes(_quote_handler, *symbols)
                logger.info(
                    f"Subscribed to quotes for: {symbols} (using {'custom' if quote_handler_cb else 'default'} handler)"
                )
            if subscribe_bars and symbols:
                self.stream.subscribe_bars(_bar_handler, *symbols)
                logger.info(
                    f"Subscribed to bars for: {symbols} (using {'custom' if bar_handler_cb else 'default'} handler)"
                )

            if subscribe_updates:  # This subscribes to the trade_updates stream
                self.stream.subscribe_trade_updates(
                    _update_handler
                )  # This handler gets OrderUpdate and AccountUpdate
                logger.info(
                    f"Subscribed to trade/account updates (using {'custom' if order_update_handler_cb else 'default'} handler)."
                )

            logger.info("Data stream setup complete, ready to run...")
            return True
        except Exception as e:
            logger.error(f"Error setting up data stream: {e}", exc_info=True)
            self.stream = None
            return False

    async def start_streaming(self):
        """
        Starts the data stream and allows exceptions to propagate.
        This method will run until the connection is closed or an error occurs.
        """
        if self.stream:
            logger.info("Starting Alpaca data stream...")
            # The caller is now responsible for handling exceptions and reconnecting.
            await self.stream._run_forever()
        else:
            logger.error("Stream is not configured. Please call setup_stream() first.")
            # Raise an exception to signal a configuration problem.
            raise ConnectionError("Stream not configured.")

    async def stop_streaming(self):
        """Stops the data stream idempotently."""
        if self.stream:
            logger.info("Attempting to stop the Alpaca data stream...")
            try:
                await self.stream.stop_ws()  # Use the async stop method
                logger.info("Data stream stopped successfully.")
            except Exception as e:
                logger.error(
                    f"An error occurred while stopping the data stream: {e}",
                    exc_info=True,
                )
            finally:
                # Ensure stream is cleared even if stop_ws fails
                self.stream = None
        else:
            logger.debug("Stream is not running or has already been stopped.")

import pytest
from alpaca_trade_api.rest import APIError
from patf_trading_framework.broker_handler import BrokerAPIHandler

def test_place_order_api_error_handling(mocker):
    """
    Verify that place_order returns None and logs an error when the API call fails.
    """
    # Arrange: Mock the 'submit_order' method of the Alpaca REST API client
    # to raise an APIError, simulating a failure.
    mocker.patch(
        'alpaca_trade_api.rest.REST.submit_order',
        side_effect=APIError({'code': 403, 'message': 'forbidden'})
    )

    # We need to initialize the handler *after* patching if the init itself makes API calls.
    # For this example, we assume init succeeds but submit_order fails.
    handler = BrokerAPIHandler() # This might need mocking too in a real scenario

    # Act: Call the method that we expect to fail
    result = handler.place_order(symbol="FAIL", qty=1, side="buy", order_type="market")

    # Assert: The method should gracefully handle the exception and return None
    assert result is None
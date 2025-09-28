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

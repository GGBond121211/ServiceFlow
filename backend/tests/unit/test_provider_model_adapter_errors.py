from serviceflow.infrastructure.gateway_errors import GatewayErrorClass
from serviceflow.infrastructure.model_gateway import _frontier_prices
from serviceflow.infrastructure.provider_model_adapters import _classify_http_status


def test_provider_http_status_classification_does_not_fallback_on_bad_request() -> None:
    assert _classify_http_status(400) is GatewayErrorClass.BAD_REQUEST
    assert _classify_http_status(404) is GatewayErrorClass.BAD_REQUEST
    assert _classify_http_status(422) is GatewayErrorClass.BAD_REQUEST
    assert _classify_http_status(429) is GatewayErrorClass.RATE_LIMIT
    assert _classify_http_status(503) is GatewayErrorClass.SERVER_ERROR
    assert GatewayErrorClass.BAD_REQUEST.fallback_allowed is False


def test_verified_frontier_prices_include_cached_input() -> None:
    assert _frontier_prices("deepseek-v4-flash") == ("12", "36", "0.3996")
    assert _frontier_prices("gpt-5.6-luna") == ("1.5", "12", "0.18")
    assert _frontier_prices("unknown-model") == (None, None, None)

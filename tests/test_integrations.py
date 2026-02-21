"""Тесты для интеграций."""

import pytest
from unittest.mock import AsyncMock, patch
from app.integrations.kupikod import KupikodIntegration
from app.integrations.plati import PlatiIntegration


@pytest.fixture
def kupikod():
    """Фикстура для KupikodIntegration."""
    return KupikodIntegration()


def test_verify_webhook(kupikod):
    """Тест проверки подписи webhook."""
    import hmac
    import hashlib

    payload = '{"test": "data"}'
    secret = kupikod.webhook_secret
    signature = hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    assert kupikod.verify_webhook(payload, signature) is True
    assert kupikod.verify_webhook(payload, "invalid") is False


def test_parse_webhook(kupikod):
    """Тест парсинга webhook."""
    payload = {
        "order_id": "123",
        "product_name": "Gems",
        "product_type": "gems",
        "game": "clash-royale",
        "amount": 10.0,
        "currency": "USD",
        "user_account": "test@example.com",
        "payment_method": "google_pay",
        "card_info": {"last4": "1234"},
    }

    result = kupikod.parse_webhook(payload)
    assert result is not None
    assert result["order_id"] == "123"
    assert result["product_name"] == "Gems"


@pytest.mark.asyncio
async def test_send_proof(kupikod):
    """Тест отправки пруфа."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_post.return_value = mock_response

        result = await kupikod.send_proof("123", {"screenshot": "test.png"})
        assert result is True

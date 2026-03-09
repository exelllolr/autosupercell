"""Тесты для Google Pay (FastSpring / Appcharge)."""

import pytest
from unittest.mock import AsyncMock

from app.core.google_pay import (
    _is_appcharge_checkout,
    _GPAY_TAB_SELECTORS,
    _APPCHARGE_BUY_GPAY_SELECTORS,
)


@pytest.mark.asyncio
async def test_is_appcharge_checkout_powered_by():
    """Appcharge определяется по тексту 'Powered by appcharge'."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value="Checkout\n1 x Fistful of Gems\n$0.99\nPowered by appcharge")
    page.url = "https://store.example.com/checkout"
    assert await _is_appcharge_checkout(page) is True


@pytest.mark.asyncio
async def test_is_appcharge_checkout_generic():
    """Appcharge определяется по слову appcharge в тексте."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value="Appcharge checkout\nPay $0.99")
    page.url = "https://example.com"
    assert await _is_appcharge_checkout(page) is True


@pytest.mark.asyncio
async def test_is_appcharge_checkout_false():
    """FastSpring страница без appcharge не определяется как Appcharge."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value="FastSpring\nPlace Your Order\nG Pay")
    page.url = "https://pay.fastspring.com/..."
    assert await _is_appcharge_checkout(page) is False


@pytest.mark.asyncio
async def test_is_appcharge_checkout_url():
    """Appcharge определяется по appcharge в URL."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value="Checkout")
    page.url = "https://appcharge.io/checkout"
    assert await _is_appcharge_checkout(page) is True


def test_gpay_tab_selectors_include_google_pay():
    """Селекторы вкладки G Pay содержат Google Pay и G Pay."""
    text_selectors = [s for s in _GPAY_TAB_SELECTORS if "Google Pay" in s or "G Pay" in s]
    assert len(text_selectors) >= 2


def test_appcharge_pay_selectors_include_place_order_and_pay():
    """Селекторы кнопки Appcharge содержат Place Your Order и Pay $."""
    has_place = any("Place Your Order" in s or "Place your order" in s for s in _APPCHARGE_BUY_GPAY_SELECTORS)
    has_pay = any("Pay $" in s for s in _APPCHARGE_BUY_GPAY_SELECTORS)
    assert has_place and has_pay

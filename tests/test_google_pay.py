"""Тесты для Google Pay (FastSpring / Appcharge)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.google_pay import (
    _is_appcharge_checkout,
    _is_google_block_page,
    _click_pay_button_inside_iframes,
    _confirm_payment_in_popup,
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


# ─── C1: _is_google_block_page ──────────────────────────────────────────────────


def test_is_google_block_page_this_browser_not_secure():
    """Блокировка «This browser or app may not be secure» определяется."""
    assert _is_google_block_page("This browser or app may not be secure") is True
    assert _is_google_block_page("Error: this browser or app may not be secure. Try again.") is True


def test_is_google_block_page_couldnt_sign_in():
    """Блокировка «Couldn't sign you in» определяется."""
    assert _is_google_block_page("Couldn't sign you in") is True
    assert _is_google_block_page("Couldn't sign you in. Try again.") is True


def test_is_google_block_page_normal_text():
    """Обычный текст не определяется как блокировка."""
    assert _is_google_block_page("Pay $0.99") is False
    assert _is_google_block_page("Sign in with Google") is False
    assert _is_google_block_page("") is False
    assert _is_google_block_page(None) is False


# ─── C2: _confirm_payment_in_popup при блокировке Google ────────────────────────


@pytest.mark.asyncio
async def test_confirm_payment_in_popup_returns_false_on_google_block():
    """При блокировке Google _confirm_payment_in_popup возвращает False."""
    popup = AsyncMock()
    popup.url = "https://pay.google.com/pay/..."
    popup.frames = [MagicMock()]
    popup.evaluate = AsyncMock(
        return_value="This browser or app may not be secure. Try again."
    )
    popup.wait_for_load_state = AsyncMock()
    popup.wait_for_timeout = AsyncMock()

    with patch("app.core.google_pay._screenshot", new_callable=AsyncMock):
        result = await _confirm_payment_in_popup(popup)
    assert result is False


# ─── C3: _click_pay_button_inside_iframes ───────────────────────────────────────


@pytest.mark.asyncio
async def test_click_pay_button_inside_iframes_fastspring_returns_false():
    """На pay.fastspring.com возвращается False (кнопка в main frame)."""
    popup = AsyncMock()
    popup.url = "https://pay.fastspring.com/checkout/..."
    popup.wait_for_timeout = AsyncMock()
    result = await _click_pay_button_inside_iframes(popup)
    assert result is False


@pytest.mark.asyncio
async def test_click_pay_button_inside_iframes_pay_google_no_iframe_returns_false():
    """На pay.google.com без iframe с кнопкой возвращается False."""
    popup = AsyncMock()
    popup.url = "https://pay.google.com/pay/..."
    popup.wait_for_url = AsyncMock()
    popup.wait_for_timeout = AsyncMock()
    # frame_locator возвращает locator с count()=0 (кнопка не найдена)
    frame_loc = MagicMock()
    pay_btn = MagicMock()
    pay_btn.count = AsyncMock(return_value=0)
    frame_loc.get_by_role.return_value.first = pay_btn
    loc = MagicMock()
    loc.count = AsyncMock(return_value=0)
    frame_loc.locator.return_value.first = loc
    popup.frame_locator.return_value = frame_loc
    popup.frames = [MagicMock()]
    popup.main_frame = MagicMock()

    with patch("app.core.google_pay._PAY_IFRAME_V2_POLL_MS", 500), patch(
        "app.core.google_pay._PAY_IFRAME_V2_INTERVAL_MS", 100
    ):
        result = await _click_pay_button_inside_iframes(popup)
    assert result is False

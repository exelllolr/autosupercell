"""Тесты для AIProductSearch."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.ai_product_search import AIProductSearch


@pytest.fixture
def mock_provider():
    """Мок AI-провайдера."""
    provider = MagicMock()
    provider.is_available.return_value = True
    provider.analyze_image = AsyncMock(
        return_value='{"found": true, "coordinates": {"x": 100, "y": 200, "width": 50, "height": 30}, "button_text": "Buy", "confidence": 0.9}'
    )
    return provider


@pytest.mark.asyncio
async def test_find_product(mock_provider, tmp_path):
    """Тест поиска товара через AI."""
    screenshot_path = tmp_path / "test.png"
    screenshot_path.write_bytes(b"fake_image_data")

    page_content = {
        "screenshot": str(screenshot_path),
        "visible_elements": [
            {"text": "Buy Gems", "x": 100, "y": 200, "width": 50, "height": 30}
        ],
    }

    search = AIProductSearch()
    search.provider = mock_provider

    result = await search.find_product(page_content, "Gems", "gems")

    assert result is not None
    assert result.get("found") is True
    assert "coordinates" in result
    mock_provider.analyze_image.assert_called_once()


@pytest.mark.asyncio
async def test_find_product_not_found(mock_provider, tmp_path):
    """Тест когда товар не найден."""
    mock_provider.analyze_image = AsyncMock(return_value='{"found": false}')

    screenshot_path = tmp_path / "test.png"
    screenshot_path.write_bytes(b"fake_image_data")

    page_content = {"screenshot": str(screenshot_path), "visible_elements": []}

    search = AIProductSearch()
    search.provider = mock_provider

    result = await search.find_product(page_content, "NonExistent", "gems")

    assert result is None


@pytest.mark.asyncio
async def test_find_product_no_provider(tmp_path):
    """Тест когда провайдер недоступен."""
    screenshot_path = tmp_path / "test.png"
    screenshot_path.write_bytes(b"fake_image_data")

    page_content = {"screenshot": str(screenshot_path), "visible_elements": []}

    search = AIProductSearch()
    search.provider = None

    result = await search.find_product(page_content, "Gems", "gems")

    assert result is None


@pytest.mark.asyncio
async def test_find_product_screenshot_missing(mock_provider, tmp_path):
    """Тест когда скриншот не существует."""
    page_content = {
        "screenshot": str(tmp_path / "nonexistent.png"),
        "visible_elements": [],
    }

    search = AIProductSearch()
    search.provider = mock_provider

    result = await search.find_product(page_content, "Gems", "gems")

    assert result is None
    mock_provider.analyze_image.assert_not_called()

"""AI-поиск товаров на странице магазина."""

from typing import Optional, Dict, List
from pathlib import Path
from loguru import logger
from app.config import settings
from app.core.ai_providers import BaseAIProvider


class AIProductSearch:
    """AI-поиск товаров с поддержкой нескольких провайдеров."""

    def __init__(self):
        """Инициализация AI поиска."""
        self.provider: Optional[BaseAIProvider] = self._get_provider()
        if not self.provider or not self.provider.is_available():
            logger.warning(
                f"AI провайдер '{settings.AI_PROVIDER}' недоступен. "
                "Проверьте настройки API ключей в .env"
            )

    def _get_provider(self) -> Optional[BaseAIProvider]:
        """Получить провайдер на основе конфигурации."""
        provider_name = settings.AI_PROVIDER.lower()

        if provider_name == "claude":
            try:
                from app.core.ai_providers.claude_provider import ClaudeProvider

                provider = ClaudeProvider()
                if provider.is_available():
                    logger.info("Используется Anthropic Claude провайдер")
                    return provider
            except ModuleNotFoundError:
                logger.warning("Anthropic (claude) пакет не установлен")
        elif provider_name == "gemini":
            try:
                from app.core.ai_providers.gemini_provider import GeminiProvider

                provider = GeminiProvider()
                if provider.is_available():
                    logger.info("Используется Google Gemini провайдер")
                    return provider
            except ModuleNotFoundError:
                logger.warning("Google Gemini пакет не установлен")
        else:  # По умолчанию OpenAI
            try:
                from app.core.ai_providers.openai_provider import OpenAIProvider

                provider = OpenAIProvider()
                if provider.is_available():
                    logger.info("Используется OpenAI провайдер")
                    return provider
            except ModuleNotFoundError:
                logger.warning("OpenAI пакет не установлен")

        return None

    async def find_product(
        self, page_content: Dict, product_name: str, product_type: str = "gems"
    ) -> Optional[Dict]:
        """
        Найти товар на странице используя AI.

        Args:
            page_content: Содержимое страницы от browser_automation
            product_name: Название товара для поиска
            product_type: Тип товара (gems, cards, etc.)

        Returns:
            Информация о найденном товаре или None
        """
        if not self.provider or not self.provider.is_available():
            logger.error("AI провайдер не доступен")
            return None

        screenshot_path = Path(page_content["screenshot"])
        if not screenshot_path.exists():
            logger.error(f"Скриншот не найден: {screenshot_path}")
            return None

        try:
            # Формируем промпт для поиска
            prompt = self._build_search_prompt(product_name, product_type, page_content)

            # Для тестов/инъекции клиента: если задан self.client, пробрасываем его в провайдер
            try:
                if hasattr(self, "client") and self.provider and hasattr(self.provider, "client"):
                    setattr(self.provider, "client", getattr(self, "client"))
            except Exception:
                pass

            # Вызываем AI провайдер
            result_text = await self.provider.analyze_image(
                str(screenshot_path), prompt
            )

            if not result_text:
                logger.error("AI провайдер не вернул результат")
                return None

            logger.info(f"AI результат поиска: {result_text[:200]}...")

            # Парсим результат
            product_info = self._parse_ai_response(result_text, page_content)
            return product_info

        except Exception as e:
            logger.error(f"Ошибка AI поиска: {e}")
            return None

    def _build_search_prompt(
        self, product_name: str, product_type: str, page_content: Dict
    ) -> str:
        """Построить промпт для AI поиска."""
        visible_texts = [
            elem["text"][:100] for elem in page_content.get("visible_elements", [])[:20]
        ]

        prompt = f"""
Ты помогаешь найти товар в игровом магазине Supercell Store.

Задача: Найди товар "{product_name}" (тип: {product_type}) на скриншоте страницы магазина.

Контекст страницы (видимые текстовые элементы):
{chr(10).join(visible_texts)}

Инструкции:
1. Внимательно изучи скриншот страницы магазина
2. Найди элемент, который соответствует товару "{product_name}"
3. Определи координаты элемента (x, y) и размеры (width, height)
4. Определи текст на кнопке покупки (например: "Buy", "Purchase", "Купить")
5. Определи цену товара, если она видна

Ответь в формате JSON:
{{
    "found": true/false,
    "coordinates": {{"x": number, "y": number, "width": number, "height": number}},
    "button_text": "текст кнопки",
    "price": "цена или null",
    "confidence": 0.0-1.0,
    "description": "описание найденного элемента"
}}

Если товар не найден, верни {{"found": false}}.
"""
        return prompt

    def _parse_ai_response(self, ai_text: str, page_content: Dict) -> Optional[Dict]:
        """Парсинг ответа AI в структурированный формат."""
        import json
        import re

        try:
            # Извлекаем JSON из ответа (поддерживаем вложенные объекты)
            text = ai_text.strip()
            result = None

            # 1) Если ответ уже JSON — парсим целиком
            try:
                if text.startswith("{") and text.endswith("}"):
                    result = json.loads(text)
            except Exception:
                result = None

            # 2) Иначе берём подстроку от первого '{' до последнего '}'
            if result is None:
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    candidate = text[start : end + 1]
                    result = json.loads(candidate)

            if result is None:
                # Пытаемся найти структурированную информацию в тексте
                result = {"found": False}

            if result.get("found"):
                # Находим соответствующий элемент на странице по координатам
                coords = result.get("coordinates", {})
                matching_element = self._find_element_by_coords(
                    page_content.get("visible_elements", []),
                    coords.get("x", 0),
                    coords.get("y", 0),
                )

                return {
                    "found": True,
                    "coordinates": coords,
                    "button_text": result.get("button_text", "Buy"),
                    "price": result.get("price"),
                    "confidence": result.get("confidence", 0.5),
                    "element": matching_element,
                    "description": result.get("description", ""),
                }
            else:
                return None

        except Exception as e:
            logger.error(f"Ошибка парсинга AI ответа: {e}")
            return None

    def _find_element_by_coords(
        self, elements: List[Dict], target_x: float, target_y: float
    ) -> Optional[Dict]:
        """Найти элемент по координатам."""
        best_match = None
        min_distance = float("inf")

        for elem in elements:
            elem_x = elem.get("x", 0) + elem.get("width", 0) / 2
            elem_y = elem.get("y", 0) + elem.get("height", 0) / 2

            distance = ((elem_x - target_x) ** 2 + (elem_y - target_y) ** 2) ** 0.5

            if distance < min_distance:
                min_distance = distance
                best_match = elem

        return best_match

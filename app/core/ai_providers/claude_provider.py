"""Anthropic Claude провайдер для AI-поиска."""

import base64
from typing import Optional
from pathlib import Path
from loguru import logger
from anthropic import AsyncAnthropic
from app.config import settings
from app.core.ai_providers.base import BaseAIProvider


class ClaudeProvider(BaseAIProvider):
    """Anthropic Claude 3.5 Sonnet провайдер."""

    def __init__(self):
        """Инициализация Claude провайдера."""
        self.api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
        if self.api_key:
            self.client = AsyncAnthropic(api_key=self.api_key)
        else:
            self.client = None
            logger.warning("Anthropic API ключ не установлен")

    def is_available(self) -> bool:
        """Проверить доступность провайдера."""
        return self.client is not None

    async def analyze_image(
        self, image_path: str, prompt: str
    ) -> Optional[str]:
        """
        Анализировать изображение с помощью Claude.

        Args:
            image_path: Путь к изображению
            prompt: Текстовый промпт

        Returns:
            Ответ от Claude или None
        """
        if not self.client:
            logger.error("Claude клиент не инициализирован")
            return None

        try:
            # Читаем изображение
            image_path_obj = Path(image_path)
            if not image_path_obj.exists():
                logger.error(f"Изображение не найдено: {image_path}")
                return None

            with open(image_path_obj, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode("utf-8")

            # Вызываем Claude API
            message = await self.client.messages.create(
                model="claude-3-5-sonnet-20241022",  # Последняя версия с Vision
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            )

            result = message.content[0].text
            logger.info(f"Claude результат: {result[:200]}...")
            return result

        except Exception as e:
            logger.error(f"Ошибка Claude API: {e}")
            return None

"""OpenAI провайдер для AI-поиска (оригинальная реализация)."""

import base64
from typing import Optional
from pathlib import Path
from loguru import logger
from openai import AsyncOpenAI
from app.config import settings
from app.core.ai_providers.base import BaseAIProvider


class OpenAIProvider(BaseAIProvider):
    """OpenAI GPT-4 Vision провайдер."""

    def __init__(self):
        """Инициализация OpenAI провайдера."""
        self.api_key = getattr(settings, "OPENAI_API_KEY", None)
        if self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key)
        else:
            self.client = None
            logger.warning("OpenAI API ключ не установлен")

    def is_available(self) -> bool:
        """Проверить доступность провайдера."""
        return self.client is not None

    async def analyze_image(
        self, image_path: str, prompt: str
    ) -> Optional[str]:
        """
        Анализировать изображение с помощью OpenAI GPT-4 Vision.

        Args:
            image_path: Путь к изображению
            prompt: Текстовый промпт

        Returns:
            Ответ от OpenAI или None
        """
        if not self.client:
            logger.error("OpenAI клиент не инициализирован")
            return None

        try:
            # Читаем изображение
            image_path_obj = Path(image_path)
            if not image_path_obj.exists():
                logger.error(f"Изображение не найдено: {image_path}")
                return None

            with open(image_path_obj, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode("utf-8")

            # Вызываем GPT-4o (обновлённая модель с vision, заменяет устаревший gpt-4-vision-preview)
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt,
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_data}",
                                },
                            },
                        ],
                    }
                ],
                max_tokens=500,
            )

            result = response.choices[0].message.content
            logger.info(f"OpenAI результат: {result[:200]}...")
            return result

        except Exception as e:
            logger.error(f"Ошибка OpenAI API: {e}")
            return None

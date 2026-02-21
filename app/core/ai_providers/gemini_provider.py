"""Google Gemini провайдер для AI-поиска."""

from typing import Optional
from pathlib import Path
from loguru import logger
import asyncio
import google.generativeai as genai
from PIL import Image
from app.config import settings
from app.core.ai_providers.base import BaseAIProvider


class GeminiProvider(BaseAIProvider):
    """Google Gemini Pro Vision провайдер."""

    def __init__(self):
        """Инициализация Gemini провайдера."""
        self.api_key = getattr(settings, "GEMINI_API_KEY", None)
        if self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                # Используем gemini-1.5-pro или gemini-1.5-flash для Vision
                self.model = genai.GenerativeModel("gemini-1.5-flash")
            except Exception as e:
                logger.error(f"Ошибка инициализации Gemini: {e}")
                self.model = None
        else:
            self.model = None
            logger.warning("Gemini API ключ не установлен")

    def is_available(self) -> bool:
        """Проверить доступность провайдера."""
        return self.model is not None

    async def analyze_image(
        self, image_path: str, prompt: str
    ) -> Optional[str]:
        """
        Анализировать изображение с помощью Gemini.

        Args:
            image_path: Путь к изображению
            prompt: Текстовый промпт

        Returns:
            Ответ от Gemini или None
        """
        if not self.model:
            logger.error("Gemini модель не инициализирована")
            return None

        try:
            # Читаем изображение
            image_path_obj = Path(image_path)
            if not image_path_obj.exists():
                logger.error(f"Изображение не найдено: {image_path}")
                return None

            # Загружаем изображение
            image = Image.open(image_path_obj)

            # Вызываем Gemini API (синхронный API, оборачиваем в executor)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content([prompt, image]),
            )

            result = response.text
            logger.info(f"Gemini результат: {result[:200]}...")
            return result

        except Exception as e:
            logger.error(f"Ошибка Gemini API: {e}")
            return None

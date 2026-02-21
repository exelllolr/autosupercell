"""Базовый класс для AI провайдеров."""

from abc import ABC, abstractmethod
from typing import Optional, Dict


class BaseAIProvider(ABC):
    """Базовый класс для всех AI провайдеров."""

    @abstractmethod
    async def analyze_image(
        self, image_path: str, prompt: str
    ) -> Optional[str]:
        """
        Анализировать изображение с помощью AI.

        Args:
            image_path: Путь к изображению
            prompt: Текстовый промпт для анализа

        Returns:
            Текстовый ответ от AI или None при ошибке
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Проверить доступность провайдера.

        Returns:
            True если провайдер настроен и доступен
        """
        pass

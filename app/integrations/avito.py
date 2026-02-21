"""Интеграция с Avito (API/manual)."""

import httpx
from typing import Dict, Optional
from loguru import logger
from app.config import settings


class AvitoIntegration:
    """Интеграция с Avito (приоритет #4)."""

    def __init__(self):
        """Инициализация интеграции с Avito."""
        self.api_key = settings.AVITO_API_KEY
        self.api_url = settings.AVITO_API_URL
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_order(self, order_id: str) -> Optional[Dict]:
        """
        Получить информацию о заказе.

        Args:
            order_id: ID заказа в Avito

        Returns:
            Информация о заказе
        """
        try:
            response = await self.client.get(
                f"{self.api_url}/orders/{order_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка получения заказа из Avito: {e}")
            return None

    async def update_order_status(
        self, order_id: str, status: str, proof_data: Optional[Dict] = None
    ) -> bool:
        """
        Обновить статус заказа.

        Args:
            order_id: ID заказа
            status: Новый статус
            proof_data: Данные пруфа

        Returns:
            Успешность обновления
        """
        try:
            payload = {"status": status}
            if proof_data:
                payload["proof"] = proof_data

            response = await self.client.patch(
                f"{self.api_url}/orders/{order_id}",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            logger.info(f"Статус заказа {order_id} обновлен на {status}")
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления статуса заказа: {e}")
            return False

    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()


avito_integration = AvitoIntegration()

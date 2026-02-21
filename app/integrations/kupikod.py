"""Интеграция с Kupikod.ru (webhook)."""

import httpx
import hmac
import hashlib
import json
from typing import Dict, Optional
from loguru import logger
from app.config import settings


class KupikodIntegration:
    """Интеграция с Kupikod.ru через webhook (приоритет #2)."""

    def __init__(self):
        """Инициализация интеграции с Kupikod."""
        self.webhook_secret = settings.KUPIKOD_WEBHOOK_SECRET
        self.api_url = settings.KUPIKOD_API_URL
        self.client = httpx.AsyncClient(timeout=30.0)

    def verify_webhook(self, payload: str, signature: str) -> bool:
        """
        Проверить подпись webhook.

        Args:
            payload: Тело запроса
            signature: Подпись из заголовка

        Returns:
            Валидность подписи
        """
        try:
            expected_signature = hmac.new(
                self.webhook_secret.encode(), payload.encode(), hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"Ошибка проверки подписи webhook: {e}")
            return False

    def parse_webhook(self, payload: Dict) -> Optional[Dict]:
        """
        Парсинг webhook от Kupikod.

        Args:
            payload: Тело webhook запроса

        Returns:
            Парсированные данные заказа
        """
        try:
            order_data = {
                "order_id": payload.get("order_id"),
                "product_name": payload.get("product_name"),
                "product_type": payload.get("product_type", "gems"),
                "game": payload.get("game", "clash-royale"),
                "amount": payload.get("amount"),
                "currency": payload.get("currency", "USD"),
                "user_account": payload.get("user_account"),
                "payment_method": payload.get("payment_method", "google_pay"),
                "card_info": payload.get("card_info", {}),
            }

            logger.info(f"Получен webhook от Kupikod: {order_data}")
            return order_data

        except Exception as e:
            logger.error(f"Ошибка парсинга webhook: {e}")
            return None

    async def send_proof(self, order_id: str, proof_data: Dict) -> bool:
        """
        Отправить пруф выполнения заказа.

        Args:
            order_id: ID заказа
            proof_data: Данные пруфа

        Returns:
            Успешность отправки
        """
        try:
            response = await self.client.post(
                f"{self.api_url}/orders/{order_id}/proof",
                json=proof_data,
                headers={"X-Webhook-Secret": self.webhook_secret},
            )
            response.raise_for_status()
            logger.info(f"Пруф для заказа {order_id} отправлен в Kupikod")
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки пруфа в Kupikod: {e}")
            return False

    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()


kupikod_integration = KupikodIntegration()

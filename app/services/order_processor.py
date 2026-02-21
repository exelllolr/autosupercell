"""Обработчик заказов - основной оркестратор."""

import asyncio
import time
from typing import Dict, Optional
from pathlib import Path
from loguru import logger
from app.core.browser_automation import BrowserAutomation
from app.core.ai_product_search import AIProductSearch
from app.core.payment_handler import PaymentHandler
from app.config import settings
from app.utils.validators import OrderValidator
from app.monitoring.metrics import (
    orders_total,
    order_processing_time,
    payments_total,
    payment_processing_time,
    ai_searches_total,
    ai_search_time,
)


class OrderProcessor:
    """Обработчик заказов - координирует весь процесс покупки."""

    def __init__(self):
        """Инициализация обработчика заказов."""
        self.browser = BrowserAutomation()
        self.ai_search = AIProductSearch()
        self.payment_handler = None

    async def process_order(self, order_data: Dict) -> Dict:
        """
        Обработать заказ от начала до конца.

        Args:
            order_data: Данные заказа
                - order_id: ID заказа
                - product_name: Название товара
                - product_type: Тип товара (gems, cards)
                - game: Игра (clash-royale, brawl-stars)
                - amount: Сумма платежа
                - currency: Валюта (USD)
                - user_account: Аккаунт пользователя
                - payment_method: Метод оплаты
                - card_info: Информация о карте

        Returns:
            Результат обработки заказа
        """
        start_time = time.time()
        order_id = order_data.get("order_id", "unknown")

        # Валидация данных заказа
        is_valid, error_message = OrderValidator.validate_order_data(order_data)
        if not is_valid:
            raise ValueError(f"Невалидные данные заказа: {error_message}")

        try:
            logger.info(f"Начало обработки заказа {order_id}")

            # 1. Запускаем браузер
            await self.browser.start()

            # 2. Переходим на страницу магазина
            game = order_data.get("game", "clash-royale")
            await self.browser.navigate_to_store(game)

            # 3. Ищем товар с помощью AI
            ai_search_start = time.time()
            page_content = await self.browser.get_page_content()
            product_name = order_data.get("product_name", "")
            product_type = order_data.get("product_type", "gems")

            product_info = await self.ai_search.find_product(
                page_content, product_name, product_type
            )
            ai_search_duration = time.time() - ai_search_start
            ai_search_time.observe(ai_search_duration)

            if product_info and product_info.get("found"):
                ai_searches_total.labels(status="success").inc()
            else:
                ai_searches_total.labels(status="not_found").inc()

            if not product_info or not product_info.get("found"):
                raise Exception(f"Товар '{product_name}' не найден на странице")

            # 4. Кликаем на товар/кнопку покупки
            button_text = product_info.get("button_text", "Buy")
            clicked = await self.browser.click_element_by_text(button_text, partial=True)

            if not clicked:
                # Пробуем кликнуть по координатам
                coords = product_info.get("coordinates", {})
                if coords:
                    page = self.browser.page
                    if page:
                        x = coords.get("x", 0) + coords.get("width", 0) / 2
                        y = coords.get("y", 0) + coords.get("height", 0) / 2
                        await page.click(f"x={x},y={y}")
                        logger.info(f"Клик по координатам: ({x}, {y})")

            await asyncio.sleep(2)

            # 5. Обрабатываем платеж
            payment_start = time.time()
            self.payment_handler = PaymentHandler(self.browser)
            payment_result = await self.payment_handler.process_payment(
                payment_method=order_data.get("payment_method", "google_pay"),
                card_info=order_data.get("card_info", {}),
                amount=order_data.get("amount", 0),
            )
            payment_duration = time.time() - payment_start
            payment_processing_time.labels(
                method=order_data.get("payment_method", "google_pay")
            ).observe(payment_duration)

            if payment_result.get("success"):
                payments_total.labels(
                    status="success",
                    method=order_data.get("payment_method", "google_pay"),
                ).inc()
            else:
                payments_total.labels(
                    status="failed",
                    method=order_data.get("payment_method", "google_pay"),
                ).inc()

            if not payment_result.get("success"):
                raise Exception(f"Ошибка платежа: {payment_result.get('error')}")

            # 6. Формируем пруф
            proof_data = {
                "screenshot": payment_result.get("screenshot"),
                "purchase_history": payment_result.get("purchase_history", []),
                "order_id": order_id,
                "timestamp": time.time(),
            }

            # Сохраняем пруф в файл
            proof_path = self._save_proof(order_id, proof_data)
            proof_data["proof_file"] = str(proof_path)

            # 7. Вычисляем TTL
            elapsed_time = time.time() - start_time
            ttl_seconds = int(elapsed_time)

            result = {
                "success": True,
                "order_id": order_id,
                "ttl_seconds": ttl_seconds,
                "proof": proof_data,
                "product_info": product_info,
            }

            # Обновляем метрики
            orders_total.labels(
                status="success", source=order_data.get("source", "unknown")
            ).inc()
            order_processing_time.labels(status="success").observe(ttl_seconds)

            logger.info(
                f"Заказ {order_id} успешно обработан за {ttl_seconds} секунд"
            )

            return result

        except Exception as e:
            logger.error(f"Ошибка обработки заказа {order_id}: {e}")
            elapsed_time = time.time() - start_time

            # Делаем скриншот ошибки
            try:
                error_screenshot = await self.browser.take_screenshot(
                    f"error_{order_id}.png"
                )
            except Exception:
                error_screenshot = None

            # Обновляем метрики ошибки
            orders_total.labels(
                status="failed", source=order_data.get("source", "unknown")
            ).inc()
            order_processing_time.labels(status="failed").observe(elapsed_time)

            return {
                "success": False,
                "order_id": order_id,
                "error": str(e),
                "ttl_seconds": int(elapsed_time),
                "screenshot": str(error_screenshot) if error_screenshot else None,
            }

        finally:
            # Закрываем браузер
            await self.browser.close()

    def _save_proof(self, order_id: str, proof_data: Dict) -> Path:
        """Сохранить пруф в файл."""
        import json

        proof_dir = Path("proofs")
        proof_dir.mkdir(exist_ok=True)

        proof_file = proof_dir / f"proof_{order_id}.json"
        with open(proof_file, "w", encoding="utf-8") as f:
            json.dump(proof_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Пруф сохранен: {proof_file}")
        return proof_file

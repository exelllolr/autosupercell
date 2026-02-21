"""Валидаторы для проверки данных заказов."""

from typing import Dict, Optional
from pydantic import BaseModel, validator
from loguru import logger


class OrderValidator:
    """Валидатор данных заказа."""

    @staticmethod
    def validate_order_data(order_data: Dict) -> tuple[bool, Optional[str]]:
        """
        Валидация данных заказа.

        Args:
            order_data: Данные заказа

        Returns:
            (is_valid, error_message)
        """
        required_fields = [
            "order_id",
            "product_name",
            "amount",
            "user_account",
            "payment_method",
            "card_info",
        ]

        # Проверка обязательных полей
        for field in required_fields:
            if field not in order_data:
                return False, f"Отсутствует обязательное поле: {field}"

        # Валидация суммы
        amount = order_data.get("amount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            return False, "Сумма должна быть положительным числом"

        # Валидация метода оплаты
        payment_method = order_data.get("payment_method")
        valid_methods = ["google_pay"]
        if payment_method not in valid_methods:
            return False, f"Неподдерживаемый метод оплаты: {payment_method}"

        # Валидация игры
        game = order_data.get("game", "clash-royale")
        valid_games = ["clash-royale", "brawl-stars"]
        if game not in valid_games:
            return False, f"Неподдерживаемая игра: {game}"

        # Валидация типа товара
        product_type = order_data.get("product_type", "gems")
        valid_types = ["gems", "cards", "coins"]
        if product_type not in valid_types:
            return False, f"Неподдерживаемый тип товара: {product_type}"

        # Валидация информации о карте
        card_info = order_data.get("card_info", {})
        if not isinstance(card_info, dict):
            return False, "card_info должен быть словарем"

        return True, None

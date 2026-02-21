"""Обработка платежей через Google Pay."""

from typing import Optional, Dict, List
from loguru import logger
from app.config import settings
from app.core.browser_automation import BrowserAutomation


class PaymentHandler:
    """Обработчик платежей через Google Pay."""

    def __init__(self, browser: BrowserAutomation):
        """
        Инициализация обработчика платежей.

        Args:
            browser: Экземпляр браузерной автоматизации
        """
        self.browser = browser

    async def process_payment(
        self, payment_method: str, card_info: Dict, amount: float
    ) -> Dict:
        """
        Обработать платеж.

        Args:
            payment_method: Метод оплаты (google_pay, etc.)
            card_info: Информация о карте
            amount: Сумма платежа

        Returns:
            Результат платежа
        """
        if payment_method == "google_pay":
            return await self._process_google_pay(card_info, amount)
        else:
            raise ValueError(f"Неподдерживаемый метод оплаты: {payment_method}")

    async def _process_google_pay(self, card_info: Dict, amount: float) -> Dict:
        """
        Обработать платеж через Google Pay.

        Args:
            card_info: Информация о карте
            amount: Сумма платежа

        Returns:
            Результат платежа
        """
        page = self.browser.page
        if not page:
            raise RuntimeError("Страница не инициализирована")

        try:
            logger.info(f"Начало обработки платежа Google Pay на сумму ${amount}")

            # Ожидаем появления формы оплаты
            await page.wait_for_selector(
                'button:has-text("Google Pay"), [data-testid*="google-pay"], .google-pay-button',
                timeout=30000,
            )

            # Кликаем на Google Pay
            google_pay_selectors = [
                'button:has-text("Google Pay")',
                '[data-testid*="google-pay"]',
                ".google-pay-button",
                'button[aria-label*="Google Pay"]',
            ]

            clicked = False
            for selector in google_pay_selectors:
                try:
                    await page.click(selector, timeout=5000)
                    clicked = True
                    logger.info(f"Клик по Google Pay выполнен: {selector}")
                    break
                except Exception:
                    continue

            if not clicked:
                raise Exception("Кнопка Google Pay не найдена")

            await page.wait_for_timeout(2000)

            # Выбираем карту, если нужно
            if card_info.get("card_id"):
                await self._select_card(card_info["card_id"])

            # Подтверждаем платеж
            await self._confirm_payment()

            # Проверяем, что карта не привязалась к аккаунту
            await self._check_and_unlink_card(card_info)

            # Ждем подтверждения платежа
            await page.wait_for_timeout(3000)

            # Делаем скриншот успеха
            screenshot_path = await self.browser.take_screenshot("payment_success.png")

            # Получаем историю покупок для пруфа
            purchase_history = await self._get_purchase_history()

            logger.info("Платеж успешно обработан")

            return {
                "success": True,
                "screenshot": str(screenshot_path),
                "purchase_history": purchase_history,
                "amount": amount,
            }

        except Exception as e:
            logger.error(f"Ошибка обработки платежа: {e}")
            screenshot_path = await self.browser.take_screenshot("payment_error.png")
            return {
                "success": False,
                "error": str(e),
                "screenshot": str(screenshot_path),
            }

    async def _select_card(self, card_id: str) -> None:
        """Выбрать карту для оплаты."""
        page = self.browser.page
        if not page:
            return

        try:
            card_selector = f'[data-card-id="{card_id}"], .card-item:has-text("{card_id}")'
            await page.click(card_selector, timeout=10000)
            logger.info(f"Карта {card_id} выбрана")
            await page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"Не удалось выбрать карту: {e}")

    async def _confirm_payment(self) -> None:
        """Подтвердить платеж."""
        page = self.browser.page
        if not page:
            return

        try:
            # Ищем кнопку подтверждения
            confirm_selectors = [
                'button:has-text("Confirm")',
                'button:has-text("Pay")',
                'button:has-text("Complete")',
                '[data-testid*="confirm"]',
                '[data-testid*="pay"]',
            ]

            for selector in confirm_selectors:
                try:
                    await page.click(selector, timeout=5000)
                    logger.info(f"Платеж подтвержден: {selector}")
                    await page.wait_for_timeout(2000)
                    return
                except Exception:
                    continue

            raise Exception("Кнопка подтверждения не найдена")

        except Exception as e:
            logger.error(f"Ошибка подтверждения платежа: {e}")
            raise

    async def _check_and_unlink_card(self, card_info: Dict) -> None:
        """
        Проверить и отвязать карту от аккаунта, если она привязалась.

        Args:
            card_info: Информация о карте
        """
        page = self.browser.page
        if not page:
            return

        try:
            # Переходим в настройки платежей
            await page.goto(
                "https://payments.google.com/paymentmethods", wait_until="networkidle"
            )
            await page.wait_for_timeout(2000)

            # Проверяем наличие карты в сохраненных методах
            card_last4 = card_info.get("last4", "")
            if card_last4:
                saved_card = await page.query_selector(
                    f'[data-card-number*="{card_last4}"]'
                )

                if saved_card:
                    logger.warning("Карта обнаружена в сохраненных методах, удаляем")
                    await saved_card.click()
                    await page.wait_for_timeout(1000)

                    delete_button = await page.query_selector(
                        'button:has-text("Remove"), button:has-text("Delete")'
                    )
                    if delete_button:
                        await delete_button.click()
                        await page.wait_for_timeout(1000)
                        logger.info("Карта успешно удалена из сохраненных методов")

        except Exception as e:
            logger.warning(f"Ошибка проверки/удаления карты: {e}")

    async def _get_purchase_history(self) -> List[Dict]:
        """Получить историю покупок для пруфа."""
        page = self.browser.page
        if not page:
            return []

        try:
            # Переходим в историю покупок Google Play
            await page.goto(
                "https://play.google.com/store/account/orderhistory",
                wait_until="networkidle",
            )
            await page.wait_for_timeout(2000)

            # Извлекаем последние покупки
            purchases = await page.evaluate(
                """
                () => {
                    const items = document.querySelectorAll('[data-order-item]');
                    const purchases = [];
                    items.forEach(item => {
                        purchases.push({
                            date: item.querySelector('.date')?.textContent || '',
                            item: item.querySelector('.item-name')?.textContent || '',
                            amount: item.querySelector('.amount')?.textContent || ''
                        });
                    });
                    return purchases.slice(0, 5);
                }
                """
            )

            return purchases

        except Exception as e:
            logger.error(f"Ошибка получения истории покупок: {e}")
            return []

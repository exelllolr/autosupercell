"""
Интеграция с FunPay через golden_key (неофициальный API).

FunPay не имеет официального REST API для продавцов. Реальная работа строится
через HTTP-запросы с cookie golden_key — тот же механизм, что использует браузер.

Реализует:
  - get_orders()              — список новых заказов продавца
  - get_chat_messages()       — сообщения чата по order_id / chat_id
  - send_chat_message()       — ответ покупателю в чат
  - raise_order()             — поднять заказ как выполненный (confirm)
  - update_order_status()     — обновить статус (completed / failed)
  - get_csrf_token()          — актуальный CSRF-токен (нужен для POST)
"""

import re
import json
import asyncio
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from loguru import logger


FUNPAY_BASE = "https://funpay.com"

# Маппинг статусов FunPay (числовые коды из HTML)
ORDER_STATUS_PAID = 0       # Оплачен, ожидает выполнения
ORDER_STATUS_CONFIRMED = 1  # Подтверждён продавцом
ORDER_STATUS_DISPUTE = 2    # Спор
ORDER_STATUS_REFUND = 3     # Возврат


class FunPayClient:
    """
    Клиент FunPay на основе golden_key cookie.

    golden_key — это значение cookie с таким же именем, видное в браузере
    на funpay.com после входа в аккаунт (DevTools → Application → Cookies).
    """

    def __init__(self, golden_key: str):
        if not golden_key:
            raise ValueError("golden_key не может быть пустым")
        self.golden_key = golden_key
        # app_cookie — вторая cookie, которую FunPay устанавливает при входе.
        # Получается автоматически при первом запросе (см. _ensure_app_cookie).
        self._app_cookie: str = ""
        self._csrf_token: str = ""
        self._user_id: Optional[int] = None
        self._username: Optional[str] = None
        self._last_csrf_refresh: float = 0.0

        self._client = httpx.AsyncClient(
            base_url=FUNPAY_BASE,
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

    # ─────────────────────────────── внутренние методы ───────────────────────

    def _cookies(self) -> Dict[str, str]:
        """Собрать актуальные cookies для запроса."""
        c = {"golden_key": self.golden_key}
        if self._app_cookie:
            c["PHPSESSID"] = self._app_cookie
        return c

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        """GET-запрос с автоматическими cookies."""
        return await self._client.get(
            path, cookies=self._cookies(), **kwargs
        )

    async def _post(self, path: str, data: dict, **kwargs) -> httpx.Response:
        """POST-запрос с CSRF-токеном и cookies."""
        csrf = await self.get_csrf_token()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": FUNPAY_BASE + "/",
            "x-csrf-token": csrf,
        }
        return await self._client.post(
            path,
            data=data,
            cookies=self._cookies(),
            headers=headers,
            **kwargs,
        )

    async def _ensure_session(self) -> None:
        """
        Инициализировать сессию: получить PHPSESSID и CSRF-токен
        с главной страницы FunPay.
        """
        try:
            resp = await self._get("/")
            # FunPay устанавливает PHPSESSID через Set-Cookie
            for name, value in resp.cookies.items():
                if name.upper() in ("PHPSESSID", "PHPSESSID"):
                    self._app_cookie = value
            self._parse_csrf_from_html(resp.text)
            self._parse_user_info(resp.text)
            logger.debug(f"FunPay сессия: user_id={self._user_id}, username={self._username}")
        except Exception as e:
            logger.error(f"Ошибка инициализации сессии FunPay: {e}")
            raise

    def _parse_csrf_from_html(self, html: str) -> None:
        """Извлечь CSRF-токен из HTML страницы."""
        # Вариант 1: meta-тег
        m = re.search(r'<meta\s+name=["\']csrf-token["\'][^>]*content=["\']([\w\-]+)', html)
        if m:
            self._csrf_token = m.group(1)
            self._last_csrf_refresh = time.time()
            return
        # Вариант 2: JS переменная
        m = re.search(r'csrf\s*[:=]\s*["\']([\w\-]+)', html)
        if m:
            self._csrf_token = m.group(1)
            self._last_csrf_refresh = time.time()
            return
        # Вариант 3: data-атрибут
        m = re.search(r'data-csrf=["\']([\w\-]+)', html)
        if m:
            self._csrf_token = m.group(1)
            self._last_csrf_refresh = time.time()

    def _parse_user_info(self, html: str) -> None:
        """Извлечь user_id и username из HTML."""
        # user_id в атрибутах или JS
        m = re.search(r'"userId"\s*:\s*(\d+)', html)
        if not m:
            m = re.search(r'data-user-id=["\'"](\d+)', html)
        if m:
            self._user_id = int(m.group(1))

        m = re.search(r'"username"\s*:\s*"([^"]+)"', html)
        if not m:
            m = re.search(r'data-username=["\'"]([^"\']+)', html)
        if m:
            self._username = m.group(1)

    async def get_csrf_token(self) -> str:
        """Получить актуальный CSRF-токен (кеш 5 минут)."""
        if self._csrf_token and (time.time() - self._last_csrf_refresh) < 300:
            return self._csrf_token
        await self._ensure_session()
        return self._csrf_token

    # ─────────────────────────────── публичные методы ────────────────────────

    async def whoami(self) -> Optional[Dict]:
        """Вернуть информацию о текущем аккаунте (проверка golden_key)."""
        try:
            await self._ensure_session()
            if self._user_id:
                return {"user_id": self._user_id, "username": self._username}
            return None
        except Exception as e:
            logger.error(f"FunPay whoami ошибка: {e}")
            return None

    async def get_orders(self, status: str = "paid") -> List[Dict]:
        """
        Получить список заказов продавца.

        Args:
            status: 'paid' — оплаченные (ожидают выполнения), 'all' — все.

        Returns:
            Список словарей с полями:
              order_id, title, buyer_name, buyer_id,
              amount, currency, created_at, status_raw
        """
        try:
            resp = await self._get("/orders/trade")
            if resp.status_code != 200:
                logger.error(f"FunPay orders HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            orders = []

            # Каждый заказ — строка таблицы с классом order-row или tr[data-id]
            rows = soup.select("tr[data-id]")
            if not rows:
                # Альтернативная разметка
                rows = soup.select(".tc-item")

            for row in rows:
                try:
                    order_id = (
                        row.get("data-id")
                        or row.get("data-order-id")
                        or ""
                    )
                    if not order_id:
                        continue

                    # Статус заказа
                    status_el = row.select_one(".tc-status, .order-status, [class*='status']")
                    status_text = status_el.get_text(strip=True).lower() if status_el else ""

                    # Фильтруем по статусу
                    is_paid = any(w in status_text for w in ("оплач", "paid", "ожидает", "новый", "new"))
                    if status == "paid" and not is_paid:
                        continue

                    # Название лота / товара
                    title_el = row.select_one(".tc-desc, .order-title, [class*='desc']")
                    title = title_el.get_text(strip=True) if title_el else ""

                    # Покупатель
                    buyer_el = row.select_one(".tc-buyer, [class*='buyer'], .username")
                    buyer_name = buyer_el.get_text(strip=True) if buyer_el else ""

                    # Сумма
                    amount_el = row.select_one(".tc-price, .amount, [class*='price']")
                    amount_str = amount_el.get_text(strip=True) if amount_el else "0"
                    amount_clean = re.sub(r"[^\d.,]", "", amount_str).replace(",", ".")
                    try:
                        amount = float(amount_clean) if amount_clean else 0.0
                    except ValueError:
                        amount = 0.0

                    orders.append({
                        "order_id": str(order_id),
                        "title": title,
                        "buyer_name": buyer_name,
                        "buyer_id": None,
                        "amount": amount,
                        "currency": "RUB",
                        "status_text": status_text,
                        "created_at": datetime.utcnow().isoformat(),
                    })
                except Exception as row_err:
                    logger.debug(f"Ошибка парсинга строки заказа: {row_err}")
                    continue

            logger.info(f"FunPay: получено {len(orders)} заказов (status={status})")
            return orders

        except Exception as e:
            logger.error(f"Ошибка получения заказов FunPay: {e}")
            return []

    async def get_chat_messages(self, order_id: str) -> List[Dict]:
        """
        Получить сообщения чата по order_id.

        Returns:
            Список словарей: author, text, is_buyer, timestamp
            Сортировка: от старых к новым.
        """
        try:
            # Чат заказа на FunPay находится по URL /chat/?node=<order_id>
            # Сначала пробуем прямой URL заказа
            resp = await self._get(f"/orders/{order_id}/")
            if resp.status_code != 200:
                # Пробуем через чат
                resp = await self._get(f"/chat/?node={order_id}")

            if resp.status_code != 200:
                logger.error(f"FunPay chat HTTP {resp.status_code} для заказа {order_id}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            messages = []

            # Сообщения чата: .message-item, .chat-message, [class*='message']
            msg_els = soup.select(".message-item, .chat-message, .msg-item")
            if not msg_els:
                msg_els = soup.select("[class*='message'][class*='item']")

            for el in msg_els:
                try:
                    # Автор
                    author_el = el.select_one(".username, .author, [class*='author'], [class*='username']")
                    author = author_el.get_text(strip=True) if author_el else "unknown"

                    # Текст
                    text_el = el.select_one(".message-text, .msg-text, .text, p")
                    text = text_el.get_text(strip=True) if text_el else el.get_text(strip=True)

                    # Определяем: это покупатель или продавец?
                    classes = " ".join(el.get("class", []))
                    is_buyer = "buyer" in classes or "incoming" in classes or "left" in classes
                    is_seller = "seller" in classes or "outgoing" in classes or "right" in classes

                    # Время
                    time_el = el.select_one("time, .time, [datetime]")
                    ts = time_el.get("datetime", "") if time_el else ""

                    if text:
                        messages.append({
                            "author": author,
                            "text": text,
                            "is_buyer": is_buyer,
                            "is_seller": is_seller,
                            "timestamp": ts,
                        })
                except Exception:
                    continue

            logger.info(f"FunPay: получено {len(messages)} сообщений для заказа {order_id}")
            return messages

        except Exception as e:
            logger.error(f"Ошибка получения чата FunPay {order_id}: {e}")
            return []

    async def get_order_detail(self, order_id: str) -> Optional[Dict]:
        """
        Получить детали конкретного заказа (название лота, сумма, покупатель).
        """
        try:
            resp = await self._get(f"/orders/{order_id}/")
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Название лота
            title_el = (
                soup.select_one("h1.page-title")
                or soup.select_one(".order-title")
                or soup.select_one("h1")
            )
            title = title_el.get_text(strip=True) if title_el else ""

            # Покупатель
            buyer_el = soup.select_one(".buyer-username, [class*='buyer'] .username")
            buyer = buyer_el.get_text(strip=True) if buyer_el else ""

            # Сумма
            amount_el = soup.select_one(".order-sum, .amount-rub, [class*='amount']")
            amount_str = amount_el.get_text(strip=True) if amount_el else ""
            amount_clean = re.sub(r"[^\d.,]", "", amount_str).replace(",", ".")
            try:
                amount = float(amount_clean) if amount_clean else 0.0
            except ValueError:
                amount = 0.0

            # Описание (иногда содержит инструкцию покупателя)
            desc_el = soup.select_one(".order-description, .lot-description")
            description = desc_el.get_text(strip=True) if desc_el else ""

            # Сообщения чата
            messages = await self.get_chat_messages(order_id)

            return {
                "order_id": order_id,
                "title": title,
                "description": description,
                "buyer_name": buyer,
                "amount": amount,
                "currency": "RUB",
                "messages": messages,
            }

        except Exception as e:
            logger.error(f"Ошибка получения деталей заказа {order_id}: {e}")
            return None

    async def send_chat_message(self, order_id: str, text: str) -> bool:
        """
        Отправить сообщение в чат заказа.

        Args:
            order_id: ID заказа
            text: Текст сообщения

        Returns:
            True если отправлено успешно
        """
        try:
            # FunPay принимает сообщения через AJAX endpoint
            data = {
                "node_id": order_id,
                "text": text,
                "html": "0",
            }
            resp = await self._post("/chat/add/", data=data)
            if resp.status_code == 200:
                result = resp.json() if resp.content else {}
                if result.get("error") == 0 or result.get("success"):
                    logger.info(f"FunPay: сообщение отправлено в заказ {order_id}")
                    return True
                else:
                    logger.warning(f"FunPay send_message ответ: {result}")
                    return False
            else:
                logger.error(f"FunPay send_message HTTP {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения FunPay {order_id}: {e}")
            return False

    async def confirm_order(self, order_id: str) -> bool:
        """
        Подтвердить выполнение заказа (поднять заказ).
        Эквивалентно нажатию кнопки «Подтвердить выдачу» в интерфейсе.

        Returns:
            True если подтверждение прошло
        """
        try:
            data = {
                "order_id": order_id,
                "action": "confirm",
            }
            resp = await self._post("/orders/trade/confirm/", data=data)
            if resp.status_code == 200:
                logger.info(f"FunPay: заказ {order_id} подтверждён")
                return True
            else:
                logger.error(f"FunPay confirm_order HTTP {resp.status_code}: {resp.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"Ошибка подтверждения заказа FunPay {order_id}: {e}")
            return False

    async def update_order_status(
        self,
        order_id: str,
        status: str,
        proof_data: Optional[Dict] = None,
    ) -> bool:
        """
        Обновить статус заказа и опционально отправить пруф в чат.

        Args:
            order_id: ID заказа FunPay
            status:   'completed' | 'failed' | 'pending'
            proof_data: {screenshot, message, url} — данные пруфа для чата

        Returns:
            True если обновление прошло успешно
        """
        success = True

        if status == "completed":
            # 1. Подтверждаем выдачу
            confirmed = await self.confirm_order(order_id)
            if not confirmed:
                logger.warning(f"FunPay: не удалось подтвердить заказ {order_id}, продолжаем...")
                success = False

            # 2. Отправляем пруф в чат
            if proof_data:
                msg_parts = ["✅ Заказ выполнен!"]
                if proof_data.get("message"):
                    msg_parts.append(proof_data["message"])
                if proof_data.get("url"):
                    msg_parts.append(f"Страница покупки: {proof_data['url']}")
                if proof_data.get("screenshot"):
                    msg_parts.append(f"Скриншот: {proof_data['screenshot']}")
                msg_text = "\n".join(msg_parts)
                await self.send_chat_message(order_id, msg_text)

        elif status == "failed":
            # Сообщаем покупателю об ошибке
            error_msg = "❌ Не удалось выполнить заказ автоматически."
            if proof_data and proof_data.get("error"):
                error_msg += f"\nПричина: {proof_data['error']}"
            error_msg += "\nОбратитесь к продавцу для уточнения."
            await self.send_chat_message(order_id, error_msg)

        return success

    async def close(self) -> None:
        """Закрыть HTTP клиент."""
        await self._client.aclose()


# ─────────────────────────────── синглтон ─────────────────────────────────────

def _create_integration() -> "FunPayIntegration":
    """Фабрика — создаёт объект с нужным бэкендом в зависимости от конфига."""
    try:
        from app.config import settings
        golden_key = getattr(settings, "FUNPAY_GOLDEN_KEY", "") or ""
        if golden_key:
            return FunPayIntegration(golden_key=golden_key)
    except Exception:
        pass
    return FunPayIntegration(golden_key="")


class FunPayIntegration:
    """
    Адаптер для совместимости со старым интерфейсом arq_worker.py.
    Делегирует реальные вызовы FunPayClient.
    """

    def __init__(self, golden_key: str = ""):
        self._golden_key = golden_key
        self._client: Optional[FunPayClient] = None

    def _get_client(self) -> FunPayClient:
        if not self._client:
            if not self._golden_key:
                raise RuntimeError(
                    "FUNPAY_GOLDEN_KEY не задан в .env. "
                    "Добавьте FUNPAY_GOLDEN_KEY=<ваш_ключ> в .env файл."
                )
            self._client = FunPayClient(self._golden_key)
        return self._client

    async def get_order(self, order_id: str) -> Optional[Dict]:
        return await self._get_client().get_order_detail(order_id)

    async def get_orders(self, status: str = "paid") -> List[Dict]:
        return await self._get_client().get_orders(status)

    async def get_chat_messages(self, order_id: str) -> List[Dict]:
        return await self._get_client().get_chat_messages(order_id)

    async def send_chat_message(self, order_id: str, text: str) -> bool:
        return await self._get_client().send_chat_message(order_id, text)

    async def confirm_order(self, order_id: str) -> bool:
        return await self._get_client().confirm_order(order_id)

    async def update_order_status(
        self,
        order_id: str,
        status: str,
        proof_data: Optional[Dict] = None,
    ) -> bool:
        return await self._get_client().update_order_status(order_id, status, proof_data)

    async def whoami(self) -> Optional[Dict]:
        return await self._get_client().whoami()

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None


# Глобальный экземпляр — импортируется из других модулей
funpay_integration = _create_integration()
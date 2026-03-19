"""
Интеграция с FunPay через golden_key (неофициальный API).

FunPay не имеет официального REST API для продавцов. Реальная работа строится
через HTTP-запросы с cookie golden_key — тот же механизм, что использует браузер.

Реализует:
  - get_orders()              — список новых заказов продавца
  - get_chat_messages()       — сообщения чата по order_id / chat_id
  - send_chat_message()       — ответ покупателю в чат
  - confirm_order()           — поднять заказ как выполненный
  - update_order_status()     — обновить статус (completed / failed)
  - get_csrf_token()          — актуальный CSRF-токен
"""

import re
import json
import asyncio
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup
from loguru import logger


FUNPAY_BASE = "https://funpay.com"

ORDER_STATUS_PAID = 0
ORDER_STATUS_CONFIRMED = 1
ORDER_STATUS_DISPUTE = 2
ORDER_STATUS_REFUND = 3


class FunPayClient:
    """
    Клиент FunPay на основе golden_key cookie.

    golden_key — значение cookie с таким же именем, видное в браузере
    на funpay.com после входа (DevTools → Application → Cookies).
    """

    def __init__(self, golden_key: str):
        if not golden_key:
            raise ValueError("golden_key не может быть пустым")
        self.golden_key = golden_key
        self._app_cookie: str = ""
        self._csrf_token: str = ""
        self._user_id: Optional[int] = None
        self._username: Optional[str] = None
        self._last_csrf_refresh: float = 0.0
        self._order_chat_id_cache: Dict[str, int] = {}

        self._client = httpx.AsyncClient(
            base_url=FUNPAY_BASE,
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/146.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Origin": "https://funpay.com",
            },
        )

    # ─────────────────────────── внутренние методы ───────────────────────────

    def _cookies(self) -> Dict[str, str]:
        c = {"golden_key": self.golden_key}
        if self._app_cookie:
            c["PHPSESSID"] = self._app_cookie
        return c

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        return await self._client.get(path, cookies=self._cookies(), **kwargs)

    async def _post_form(self, path: str, data: dict, referer: str = "/") -> httpx.Response:
        """
        POST с application/x-www-form-urlencoded — именно так браузер
        отправляет данные в /runner/ и другие endpoint-ы FunPay.
        """
        csrf = await self.get_csrf_token()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": FUNPAY_BASE + referer,
            "x-csrf-token": csrf,
            "Origin": "https://funpay.com",
        }
        return await self._client.post(
            path,
            data=data,
            cookies=self._cookies(),
            headers=headers,
        )

    async def _ensure_session(self) -> None:
        """
        Инициализация сессии: PHPSESSID + CSRF с главной страницы.
        FunPay хранит CSRF в JS-переменной app.Csrf, не в meta-теге.
        """
        try:
            resp = await self._get("/")
            for name, value in resp.cookies.items():
                if name.upper() == "PHPSESSID":
                    self._app_cookie = value

            self._parse_csrf_from_html(resp.text)
            self._parse_user_info(resp.text)
            logger.debug(
                f"FunPay сессия: user_id={self._user_id}, "
                f"username={self._username}, csrf={self._csrf_token[:10] if self._csrf_token else 'НЕ НАЙДЕН'}..."
            )
        except Exception as e:
            logger.error(f"Ошибка инициализации сессии FunPay: {e}")
            raise

    def _parse_csrf_from_html(self, html: str) -> None:
        """
        Извлечь CSRF-токен из HTML.
        FunPay хранит его в JS: app.Csrf = "TOKEN"
        """
        patterns = [
            # Основной: app.Csrf = "TOKEN" в JS
            r'app\.Csrf\s*=\s*["\']([a-f0-9]+)["\']',
            # Вариант: window.csrfToken = "TOKEN"
            r'window\.csrfToken\s*=\s*["\']([a-f0-9]+)["\']',
            # Вариант: "csrf":"TOKEN" в JSON конфиге
            r'"csrf"\s*:\s*"([a-f0-9]+)"',
            # Вариант: csrf_token = "TOKEN"
            r'csrf_token\s*=\s*["\']([a-f0-9]+)["\']',
            # Вариант: data-csrf атрибут
            r'data-csrf=["\']([a-f0-9]+)["\']',
            # Вариант: meta csrf-token
            r'<meta\s+name=["\']csrf-token["\'][^>]*content=["\']([\w\-]+)',
            # Последний: hex-строка 32+ символов рядом с "csrf"
            r'["\']csrf["\']:\s*["\']([a-f0-9]{32,})["\']',
        ]

        for pattern in patterns:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                self._csrf_token = m.group(1)
                self._last_csrf_refresh = time.time()
                logger.debug(f"CSRF найден: {self._csrf_token[:10]}...")
                return

        logger.warning("CSRF токен не найден ни одним паттерном")

    def _parse_user_info(self, html: str) -> None:
        patterns_id = [
            r'/users/(\d+)/',
            r'"userId"\s*:\s*(\d+)',
            r'app\.UserId\s*=\s*(\d+)',
            r'user_id\s*[:=]\s*(\d+)',
        ]
        for p in patterns_id:
            m = re.search(p, html)
            if m:
                self._user_id = int(m.group(1))
                break

        patterns_name = [
            r'class="user-link-name"[^>]*>([^<]+)<',
            r'"username"\s*:\s*"([^"]+)"',
            r'app\.Username\s*=\s*["\']([^"\']+)["\']',
        ]
        for p in patterns_name:
            m = re.search(p, html)
            if m:
                self._username = m.group(1).strip()
                break

    async def get_csrf_token(self) -> str:
        """Получить актуальный CSRF-токен (кеш 5 минут)."""
        if self._csrf_token and (time.time() - self._last_csrf_refresh) < 300:
            return self._csrf_token
        await self._ensure_session()
        return self._csrf_token

    async def _get_chat_node_for_order(self, order_id: str) -> Optional[int]:
        """
        Получить числовой node (chat_id) для заказа со страницы заказа.
        Кешируем результат.
        """
        if order_id in self._order_chat_id_cache:
            return self._order_chat_id_cache[order_id]

        try:
            resp = await self._get(f"/orders/{order_id}/")
            if resp.status_code != 200:
                return None
            html = resp.text

            patterns = [
                r'data-node=["\'](\d+)["\']',
                r'data-id=["\'](\d+)["\']',
                r'/chat/\?node=(\d+)',
                r'"node"\s*:\s*(\d+)',
                r'"nodeId"\s*:\s*(\d+)',
                r'data-chat=["\'](\d+)["\']',
                r'node_id\s*[:=]\s*["\']?(\d+)',
            ]
            for pattern in patterns:
                m = re.search(pattern, html)
                if m:
                    node = int(m.group(1))
                    self._order_chat_id_cache[order_id] = node
                    logger.debug(f"node для заказа {order_id}: {node}")
                    return node

            logger.warning(f"node не найден для заказа {order_id}")
            return None
        except Exception as e:
            logger.error(f"Ошибка получения node для {order_id}: {e}")
            return None

    # ─────────────────────────── публичные методы ────────────────────────────

    async def whoami(self) -> Optional[Dict]:
        try:
            await self._ensure_session()
            if self._user_id:
                return {"user_id": self._user_id, "username": self._username}
            return None
        except Exception as e:
            logger.error(f"FunPay whoami ошибка: {e}")
            return None

    async def get_orders(self, status: str = "paid") -> list:
        try:
            resp = await self._get("/orders/trade")
            if resp.status_code != 200:
                logger.error(f"FunPay orders HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            orders = []
            rows = soup.select("a.tc-item")

            for row in rows:
                try:
                    href = row.get("href", "")
                    m = re.search(r"/orders/([^/]+)/", href)
                    if not m:
                        continue
                    order_id = m.group(1)

                    classes = " ".join(row.get("class", []))
                    if "warning" in classes or "danger" in classes:
                        status_text = "dispute"
                    elif "success" in classes or "muted" in classes:
                        status_text = "completed"
                    else:
                        status_text = "paid"

                    if status == "paid" and status_text != "paid":
                        continue

                    title_el = row.select_one(".tc-desc-text, .tc-desc, [class*='desc']")
                    title = title_el.get_text(strip=True) if title_el else ""

                    buyer_el = row.select_one(".tc-buyer-text, .tc-user, [class*='buyer']")
                    buyer_name = buyer_el.get_text(strip=True) if buyer_el else ""

                    price_el = row.select_one(".tc-price div:last-child, [class*='price'] div")
                    if not price_el:
                        price_el = row.select_one(".tc-price")
                    amount_str = price_el.get_text(strip=True) if price_el else "0"
                    amount_clean = re.sub(r"[^\d.,]", "", amount_str).replace(",", ".")
                    try:
                        amount = float(amount_clean) if amount_clean else 0.0
                    except ValueError:
                        amount = 0.0

                    orders.append({
                        "order_id": order_id,
                        "title": title,
                        "buyer_name": buyer_name,
                        "buyer_id": None,
                        "amount": amount,
                        "currency": "RUB",
                        "status_text": status_text,
                        "created_at": "",
                    })
                except Exception as row_err:
                    logger.debug(f"Ошибка парсинга строки заказа: {row_err}")
                    continue

            seen = set()
            orders = [o for o in orders if not (o["order_id"] in seen or seen.add(o["order_id"]))]
            logger.info(f"FunPay: получено {len(orders)} заказов (status={status})")
            return orders

        except Exception as e:
            logger.error(f"Ошибка получения заказов FunPay: {e}")
            return []

    async def get_chat_messages(self, order_id: str) -> List[Dict]:
        try:
            resp = await self._get(f"/orders/{order_id}/")
            if resp.status_code != 200:
                resp = await self._get(f"/chat/?node={order_id}")
            if resp.status_code != 200:
                logger.error(f"FunPay chat HTTP {resp.status_code} для заказа {order_id}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            messages = []
            msg_els = soup.select(".message-item, .chat-message, .msg-item")
            if not msg_els:
                msg_els = soup.select("[class*='message'][class*='item']")

            for el in msg_els:
                try:
                    author_el = el.select_one(".username, .author, [class*='author'], [class*='username']")
                    author = author_el.get_text(strip=True) if author_el else "unknown"
                    text_el = el.select_one(".message-text, .msg-text, .text, p")
                    text = text_el.get_text(strip=True) if text_el else el.get_text(strip=True)
                    classes = " ".join(el.get("class", []))
                    is_buyer = "buyer" in classes or "incoming" in classes or "left" in classes
                    is_seller = "seller" in classes or "outgoing" in classes or "right" in classes
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
        try:
            resp = await self._get(f"/orders/{order_id}/")
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            title_el = (
                soup.select_one("h1.page-title")
                or soup.select_one(".order-title")
                or soup.select_one("h1")
            )
            title = title_el.get_text(strip=True) if title_el else ""
            buyer_el = soup.select_one(".buyer-username, [class*='buyer'] .username")
            buyer = buyer_el.get_text(strip=True) if buyer_el else ""
            amount_el = soup.select_one(".order-sum, .amount-rub, [class*='amount']")
            amount_str = amount_el.get_text(strip=True) if amount_el else ""
            amount_clean = re.sub(r"[^\d.,]", "", amount_str).replace(",", ".")
            try:
                amount = float(amount_clean) if amount_clean else 0.0
            except ValueError:
                amount = 0.0
            desc_el = soup.select_one(".order-description, .lot-description")
            description = desc_el.get_text(strip=True) if desc_el else ""
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

        Браузер FunPay использует POST /runner/ с Content-Type:
        application/x-www-form-urlencoded (НЕ JSON).

        Формат тела:
            objects=<JSON-строка>&request=false&csrf_token=<TOKEN>

        где JSON-строка:
            [{"type":"chat_message","data":{"node":<id>,"last_message":-1,"content":"<текст>"}}]
        """
        await self.get_csrf_token()

        node = await self._get_chat_node_for_order(order_id)

        if node is not None:
            success = await self._send_via_runner(node, text, order_id)
            if success:
                return True
            logger.warning(f"Заказ {order_id}: /runner/ не сработал, пробуем fallback...")

        success = await self._send_via_order_page(order_id, text)
        if success:
            return True

        logger.error(f"Заказ {order_id}: все методы отправки сообщения не сработали")
        return False

    async def _send_via_runner(self, node: int, text: str, order_id: str) -> bool:
        """
        Отправка через /runner/ — основной метод браузера FunPay.

        ВАЖНО: Content-Type = application/x-www-form-urlencoded (не JSON!).
        Поле objects содержит JSON-строку как значение form-поля.
        """
        try:
            csrf = await self.get_csrf_token()

            # objects — JSON-массив передаётся как строка внутри form-encoded тела
            objects_json = json.dumps([
                {
                    "type": "chat_message",
                    "data": {
                        "node": node,
                        "last_message": -1,
                        "content": text,
                    },
                }
            ], ensure_ascii=False)

            form_data = {
                "objects": objects_json,
                "request": "false",
                "csrf_token": csrf,
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{FUNPAY_BASE}/orders/{order_id}/",
                "x-csrf-token": csrf,
                "Origin": "https://funpay.com",
            }

            resp = await self._client.post(
                "/runner/",
                data=form_data,
                cookies=self._cookies(),
                headers=headers,
            )

            logger.debug(
                f"FunPay /runner/ HTTP {resp.status_code} | "
                f"node={node} | ответ: {resp.text[:300]}"
            )

            if resp.status_code != 200:
                logger.warning(f"FunPay /runner/ HTTP {resp.status_code}")
                return False

            response_text = resp.text.strip()

            # Пустой ответ 200 = успех
            if not response_text:
                logger.info(f"FunPay: сообщение отправлено в заказ {order_id} via /runner/ (пустой ответ)")
                return True

            try:
                result = resp.json()
                if isinstance(result, list):
                    logger.info(f"FunPay: сообщение отправлено в заказ {order_id} via /runner/")
                    return True
                if isinstance(result, dict):
                    err = result.get("error")
                    if err == 0 or result.get("success"):
                        logger.info(f"FunPay: сообщение отправлено в заказ {order_id} via /runner/")
                        return True
                    # CSRF устарел
                    if err in (1, 2) or "csrf" in str(result).lower():
                        logger.warning(f"FunPay /runner/ CSRF ошибка, обновляем: {result}")
                        self._csrf_token = ""
                        self._last_csrf_refresh = 0
                        return False
                    logger.warning(f"FunPay /runner/ ответ: {result}")
                    # Любой 200 без явной ошибки = успех
                    return True
            except Exception:
                logger.info(
                    f"FunPay: сообщение отправлено в заказ {order_id} via /runner/ "
                    f"(не-JSON 200: {response_text[:100]})"
                )
                return True

        except Exception as e:
            logger.error(f"Ошибка /runner/ для заказа {order_id}: {e}")
            return False

    async def _send_via_order_page(self, order_id: str, text: str) -> bool:
        """Fallback: POST прямо на страницу заказа."""
        try:
            csrf = await self.get_csrf_token()
            form_data = {
                "csrf_token": csrf,
                "action": "send_message",
                "order_id": order_id,
                "text": text,
                "message": text,
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{FUNPAY_BASE}/orders/{order_id}/",
                "x-csrf-token": csrf,
                "Origin": "https://funpay.com",
            }
            resp = await self._client.post(
                f"/orders/{order_id}/",
                data=form_data,
                cookies=self._cookies(),
                headers=headers,
            )
            logger.debug(f"FunPay order_page HTTP {resp.status_code} | ответ: {resp.text[:200]}")
            if resp.status_code in (200, 302):
                logger.info(f"FunPay: сообщение отправлено в заказ {order_id} (order_page fallback)")
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка order_page fallback для {order_id}: {e}")
            return False

    async def confirm_order(self, order_id: str) -> bool:
        try:
            data = {"order_id": order_id, "action": "confirm"}
            resp = await self._post_form("/orders/trade/confirm/", data=data, referer="/orders/trade")
            if resp.status_code == 200:
                logger.info(f"FunPay: заказ {order_id} подтверждён")
                return True
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
        success = True

        if status == "completed":
            confirmed = await self.confirm_order(order_id)
            if not confirmed:
                logger.warning(f"FunPay: не удалось подтвердить заказ {order_id}, продолжаем...")
                success = False
            if proof_data:
                msg_parts = ["✅ Заказ выполнен!"]
                if proof_data.get("message"):
                    msg_parts.append(proof_data["message"])
                if proof_data.get("url"):
                    msg_parts.append(f"Страница покупки: {proof_data['url']}")
                if proof_data.get("screenshot"):
                    msg_parts.append(f"Скриншот: {proof_data['screenshot']}")
                await self.send_chat_message(order_id, "\n".join(msg_parts))

        elif status == "failed":
            error_msg = "❌ Не удалось выполнить заказ автоматически."
            if proof_data and proof_data.get("error"):
                error_msg += f"\nПричина: {proof_data['error']}"
            error_msg += "\nОбратитесь к продавцу для уточнения."
            await self.send_chat_message(order_id, error_msg)

        return success

    async def close(self) -> None:
        await self._client.aclose()


# ─────────────────────────────── синглтон ────────────────────────────────────

def _create_integration() -> "FunPayIntegration":
    try:
        from app.config import settings
        golden_key = getattr(settings, "FUNPAY_GOLDEN_KEY", "") or ""
        if golden_key:
            return FunPayIntegration(golden_key=golden_key)
    except Exception:
        pass
    return FunPayIntegration(golden_key="")


class FunPayIntegration:
    """Адаптер для совместимости со старым интерфейсом."""

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


funpay_integration = _create_integration()
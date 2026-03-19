"""
Интеграция с FunPay через golden_key (неофициальный API).

Основано на реверс-инжиниринге FunPayCardinal/FunPayAPI (sidor0912):
  - CSRF получается через POST /runner/ с init-запросом (НЕ с главной страницы)
  - Сообщения отправляются через POST /runner/ с form-urlencoded телом
  - objects — JSON-строка внутри form-поля

Реализует:
  - get_orders()          — список новых заказов продавца
  - get_chat_messages()   — сообщения чата по order_id
  - send_chat_message()   — ответ покупателю в чат заказа
  - confirm_order()       — подтвердить выдачу заказа
  - update_order_status() — обновить статус (completed / failed)
"""

import re
import json
import time
import random
import string
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger


FUNPAY_BASE = "https://funpay.com"


def _random_tag() -> str:
    """Генерирует случайный 8-символьный hex-тег (как в оригинальной FunPayAPI)."""
    return "".join(random.choices(string.digits + "abcdef", k=8))


class FunPayClient:
    """
    Клиент FunPay на основе golden_key cookie.

    Ключевое отличие от предыдущих версий:
    CSRF-токен получается через POST /runner/ с init payload,
    а НЕ парсингом главной страницы. Именно так работает
    официальная библиотека FunPayAPI (FunPayCardinal).
    """

    def __init__(self, golden_key: str):
        if not golden_key:
            raise ValueError("golden_key не может быть пустым")
        self.golden_key = golden_key
        self._phpsessid: str = ""
        self._csrf_token: str = ""
        self._user_id: Optional[int] = None
        self._username: Optional[str] = None
        self._last_csrf_refresh: float = 0.0
        self._order_node_cache: Dict[str, int] = {}
        self._initiated: bool = False

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
                "Origin": "https://funpay.com",
            },
        )

    # ─────────────────────────── cookies / session ────────────────────────────

    def _cookies(self) -> Dict[str, str]:
        c = {"golden_key": self.golden_key}
        if self._phpsessid:
            c["PHPSESSID"] = self._phpsessid
        return c

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        return await self._client.get(path, cookies=self._cookies(), **kwargs)

    async def _post_runner(self, objects: list) -> httpx.Response:
        """
        POST /runner/ — основной транспорт FunPay.

        Content-Type: application/x-www-form-urlencoded
        Поле objects содержит JSON-список как строку.
        Поле csrf_token — текущий CSRF.
        """
        payload = {
            "objects": json.dumps(objects, ensure_ascii=False),
            "request": "false",
            "csrf_token": self._csrf_token,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "Referer": FUNPAY_BASE + "/",
        }
        return await self._client.post(
            "/runner/",
            data=payload,
            cookies=self._cookies(),
            headers=headers,
        )

    # ─────────────────────────── инициализация ───────────────────────────────

    async def _init_session(self) -> None:
        """
        Инициализация сессии — получение PHPSESSID и CSRF.

        Шаг 1: GET / — получаем PHPSESSID из Set-Cookie.
        Шаг 2: Парсим HTML главной страницы для user_id и username.
        Шаг 3: POST /runner/ с init payload — FunPay возвращает csrf_token
                в ответе. Именно так работает FunPayCardinal.
        """
        try:
            # Шаг 1: получаем PHPSESSID
            resp = await self._get("/")
            resp.raise_for_status()

            for name, value in resp.cookies.items():
                if name.upper() == "PHPSESSID":
                    self._phpsessid = value
                    break

            # Парсим user_id и username с главной
            self._parse_user_info(resp.text)

            # Шаг 2: Получаем CSRF через /runner/ init-запрос
            # Это точная копия того, что делает FunPayAPI при Account.get()
            init_objects = [
                {
                    "type": "orders_counters",
                    "id": str(self._user_id) if self._user_id else "0",
                    "tag": _random_tag(),
                    "data": False,
                }
            ]
            payload = {
                "objects": json.dumps(init_objects, ensure_ascii=False),
                "request": "false",
                "csrf_token": "",  # пустой при первом запросе
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "*/*",
                "Referer": FUNPAY_BASE + "/",
            }
            runner_resp = await self._client.post(
                "/runner/",
                data=payload,
                cookies=self._cookies(),
                headers=headers,
            )

            if runner_resp.status_code == 200 and runner_resp.content:
                try:
                    data = runner_resp.json()
                    # FunPay возвращает csrf_token в корне ответа
                    csrf = data.get("csrf_token") or data.get("csrfToken") or ""
                    if csrf:
                        self._csrf_token = csrf
                        self._last_csrf_refresh = time.time()
                        logger.debug(f"CSRF получен через /runner/ init: {csrf[:10]}...")
                    else:
                        logger.warning(f"csrf_token не найден в ответе /runner/: {str(data)[:200]}")
                        # Fallback: пробуем достать CSRF из HTML главной страницы
                        self._parse_csrf_from_html(resp.text)
                except Exception as e:
                    logger.warning(f"Ошибка парсинга ответа /runner/ init: {e}")
                    self._parse_csrf_from_html(resp.text)
            else:
                logger.warning(f"/runner/ init HTTP {runner_resp.status_code}, пробуем HTML fallback")
                self._parse_csrf_from_html(resp.text)

            self._initiated = True
            logger.debug(
                f"FunPay init: user_id={self._user_id}, username={self._username}, "
                f"csrf={'OK' if self._csrf_token else 'MISSING'}"
            )

        except Exception as e:
            logger.error(f"Ошибка инициализации сессии FunPay: {e}")
            raise

    def _parse_csrf_from_html(self, html: str) -> None:
        """Fallback: поиск CSRF в HTML (7 паттернов)."""
        patterns = [
            r'app\.Csrf\s*=\s*["\']([a-f0-9]+)["\']',
            r'"csrf_token"\s*:\s*"([a-f0-9]+)"',
            r'"csrf"\s*:\s*"([a-f0-9]+)"',
            r'window\.csrfToken\s*=\s*["\']([a-f0-9]+)["\']',
            r'csrf_token\s*=\s*["\']([a-f0-9]+)["\']',
            r'data-csrf=["\']([a-f0-9]+)["\']',
            r'<meta\s+name=["\']csrf-token["\'][^>]*content=["\']([\w\-]+)',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                self._csrf_token = m.group(1)
                self._last_csrf_refresh = time.time()
                logger.debug(f"CSRF (HTML fallback): {self._csrf_token[:10]}...")
                return
        logger.warning("CSRF не найден ни в /runner/ ответе, ни в HTML")

    def _parse_user_info(self, html: str) -> None:
        for p in [r'/users/(\d+)/', r'"userId"\s*:\s*(\d+)', r'app\.UserId\s*=\s*(\d+)']:
            m = re.search(p, html)
            if m:
                self._user_id = int(m.group(1))
                break
        for p in [r'class="user-link-name"[^>]*>([^<]+)<', r'"username"\s*:\s*"([^"]+)"']:
            m = re.search(p, html)
            if m:
                self._username = m.group(1).strip()
                break

    async def _ensure_session(self) -> None:
        """Инициализировать или обновить сессию (кеш 5 минут)."""
        if not self._initiated or (time.time() - self._last_csrf_refresh) > 300:
            await self._init_session()

    # ─────────────────────────── публичные методы ────────────────────────────

    async def whoami(self) -> Optional[Dict]:
        try:
            await self._ensure_session()
            if self._user_id:
                return {"user_id": self._user_id, "username": self._username}
            return None
        except Exception as e:
            logger.error(f"FunPay whoami: {e}")
            return None

    async def get_orders(self, status: str = "paid") -> List[Dict]:
        try:
            await self._ensure_session()
            resp = await self._get("/orders/trade")
            if resp.status_code != 200:
                logger.error(f"FunPay orders HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            orders = []

            for row in soup.select("a.tc-item"):
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

                    price_el = row.select_one(".tc-price div:last-child, [class*='price'] div") \
                                or row.select_one(".tc-price")
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
                except Exception as e:
                    logger.debug(f"Ошибка парсинга строки заказа: {e}")
                    continue

            seen: set = set()
            orders = [o for o in orders if not (o["order_id"] in seen or seen.add(o["order_id"]))]
            logger.info(f"FunPay: получено {len(orders)} заказов (status={status})")
            return orders

        except Exception as e:
            logger.error(f"Ошибка получения заказов FunPay: {e}")
            return []

    async def get_chat_messages(self, order_id: str) -> List[Dict]:
        try:
            await self._ensure_session()
            resp = await self._get(f"/orders/{order_id}/")
            if resp.status_code != 200:
                resp = await self._get(f"/chat/?node={order_id}")
            if resp.status_code != 200:
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
                    time_el = el.select_one("time, .time, [datetime]")
                    ts = time_el.get("datetime", "") if time_el else ""
                    if text:
                        messages.append({
                            "author": author,
                            "text": text,
                            "is_buyer": is_buyer,
                            "is_seller": not is_buyer,
                            "timestamp": ts,
                        })
                except Exception:
                    continue

            logger.info(f"FunPay: получено {len(messages)} сообщений для заказа {order_id}")
            return messages

        except Exception as e:
            logger.error(f"Ошибка получения чата {order_id}: {e}")
            return []

    async def get_order_detail(self, order_id: str) -> Optional[Dict]:
        try:
            await self._ensure_session()
            resp = await self._get(f"/orders/{order_id}/")
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            title_el = soup.select_one("h1.page-title") or soup.select_one(".order-title") or soup.select_one("h1")
            title = title_el.get_text(strip=True) if title_el else ""
            buyer_el = soup.select_one(".buyer-username, [class*='buyer'] .username")
            buyer = buyer_el.get_text(strip=True) if buyer_el else ""
            messages = await self.get_chat_messages(order_id)

            return {
                "order_id": order_id,
                "title": title,
                "description": "",
                "buyer_name": buyer,
                "amount": 0.0,
                "currency": "RUB",
                "messages": messages,
            }
        except Exception as e:
            logger.error(f"Ошибка деталей заказа {order_id}: {e}")
            return None

    async def _get_node_for_order(self, order_id: str) -> Optional[int]:
        """Получить числовой node (chat_id) для заказа."""
        if order_id in self._order_node_cache:
            return self._order_node_cache[order_id]
        try:
            resp = await self._get(f"/orders/{order_id}/")
            if resp.status_code != 200:
                return None
            html = resp.text
            for pattern in [
                r'data-node=["\'](\d+)["\']',
                r'data-id=["\'](\d+)["\']',
                r'/chat/\?node=(\d+)',
                r'"node"\s*:\s*(\d+)',
                r'"nodeId"\s*:\s*(\d+)',
                r'data-chat=["\'](\d+)["\']',
            ]:
                m = re.search(pattern, html)
                if m:
                    node = int(m.group(1))
                    self._order_node_cache[order_id] = node
                    logger.debug(f"node для заказа {order_id}: {node}")
                    return node
            return None
        except Exception as e:
            logger.error(f"Ошибка получения node для {order_id}: {e}")
            return None

    async def send_chat_message(self, order_id: str, text: str) -> bool:
        """
        Отправить сообщение в чат заказа через POST /runner/.

        Формат objects для отправки сообщения (из реверс-инжиниринга FunPayCardinal):
            [{
                "type": "chat_message",
                "id": "<node_id>",
                "tag": "<random_8_hex>",
                "data": {
                    "node": <node_id>,
                    "last_message": -1,
                    "content": "<текст>"
                }
            }]
        """
        await self._ensure_session()

        if not self._csrf_token:
            logger.error(f"Заказ {order_id}: CSRF токен отсутствует, невозможно отправить сообщение")
            return False

        node = await self._get_node_for_order(order_id)

        if node is None:
            logger.warning(f"Заказ {order_id}: node не найден, пробуем отправку без node")
            # Пробуем использовать order_id напрямую как строку-идентификатор
            return await self._send_without_node(order_id, text)

        return await self._send_with_node(node, order_id, text)

    async def _send_with_node(self, node: int, order_id: str, text: str) -> bool:
        """Отправка сообщения с известным числовым node."""
        try:
            objects = [
                {
                    "type": "chat_message",
                    "id": str(node),
                    "tag": _random_tag(),
                    "data": {
                        "node": node,
                        "last_message": -1,
                        "content": text,
                    },
                }
            ]

            resp = await self._post_runner(objects)
            logger.debug(f"/runner/ (node={node}) HTTP {resp.status_code}: {resp.text[:300]}")

            if resp.status_code != 200:
                return False

            if not resp.text.strip():
                logger.info(f"Сообщение отправлено в заказ {order_id} (пустой ответ = успех)")
                return True

            try:
                data = resp.json()
                # Обновляем CSRF если пришёл новый
                new_csrf = data.get("csrf_token") or data.get("csrfToken")
                if new_csrf:
                    self._csrf_token = new_csrf
                    self._last_csrf_refresh = time.time()

                objs = data.get("objects", [])
                for obj in objs:
                    if obj.get("type") == "chat_message" and obj.get("data"):
                        logger.info(f"✅ Сообщение отправлено в заказ {order_id} via /runner/")
                        return True

                # Нет ошибки — считаем успехом
                if not data.get("error"):
                    logger.info(f"✅ Сообщение отправлено в заказ {order_id} via /runner/ (ответ: {str(objs)[:100]})")
                    return True

                logger.warning(f"/runner/ вернул ошибку: {data}")
                return False

            except Exception:
                logger.info(f"✅ Сообщение отправлено в заказ {order_id} (не-JSON ответ 200)")
                return True

        except Exception as e:
            logger.error(f"Ошибка _send_with_node для {order_id}: {e}")
            return False

    async def _send_without_node(self, order_id: str, text: str) -> bool:
        """
        Отправка если node не найден — пробуем chat_node тип
        (FunPayCardinal использует этот тип для получения чата).
        """
        try:
            objects = [
                {
                    "type": "chat_message",
                    "id": order_id,
                    "tag": _random_tag(),
                    "data": {
                        "node": order_id,
                        "last_message": -1,
                        "content": text,
                    },
                }
            ]
            resp = await self._post_runner(objects)
            logger.debug(f"/runner/ (no node) HTTP {resp.status_code}: {resp.text[:200]}")

            if resp.status_code == 200:
                logger.info(f"Сообщение отправлено в заказ {order_id} (без node)")
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка _send_without_node: {e}")
            return False

    async def confirm_order(self, order_id: str) -> bool:
        try:
            await self._ensure_session()
            data = {
                "order_id": order_id,
                "action": "confirm",
                "csrf_token": self._csrf_token,
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{FUNPAY_BASE}/orders/{order_id}/",
            }
            resp = await self._client.post(
                "/orders/trade/confirm/",
                data=data,
                cookies=self._cookies(),
                headers=headers,
            )
            if resp.status_code == 200:
                logger.info(f"FunPay: заказ {order_id} подтверждён")
                return True
            logger.error(f"confirm_order HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"Ошибка confirm_order {order_id}: {e}")
            return False

    async def update_order_status(
        self, order_id: str, status: str, proof_data: Optional[Dict] = None
    ) -> bool:
        success = True
        if status == "completed":
            if not await self.confirm_order(order_id):
                success = False
            if proof_data:
                parts = ["✅ Заказ выполнен!"]
                if proof_data.get("message"):
                    parts.append(proof_data["message"])
                if proof_data.get("url"):
                    parts.append(f"Страница: {proof_data['url']}")
                await self.send_chat_message(order_id, "\n".join(parts))
        elif status == "failed":
            msg = "❌ Не удалось выполнить заказ автоматически."
            if proof_data and proof_data.get("error"):
                msg += f"\nПричина: {proof_data['error']}"
            msg += "\nОбратитесь к продавцу."
            await self.send_chat_message(order_id, msg)
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
    """Адаптер для совместимости с остальным кодом."""

    def __init__(self, golden_key: str = ""):
        self._golden_key = golden_key
        self._client: Optional[FunPayClient] = None

    def _get_client(self) -> FunPayClient:
        if not self._client:
            if not self._golden_key:
                raise RuntimeError("FUNPAY_GOLDEN_KEY не задан в .env")
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
        self, order_id: str, status: str, proof_data: Optional[Dict] = None
    ) -> bool:
        return await self._get_client().update_order_status(order_id, status, proof_data)

    async def whoami(self) -> Optional[Dict]:
        return await self._get_client().whoami()

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None


funpay_integration = _create_integration()
"""
Диагностика отправки сообщений FunPay.

Запуск:
    python examples/funpay_debug_chat.py ZVWPQ96F

Показывает:
  - Какой chat_id найден на странице заказа
  - Полный HTML вокруг chat/node элементов
  - Реальные ответы от всех endpoint-ов
"""

import asyncio
import os
import re
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("/root/autosupercell/.env")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import httpx
from bs4 import BeautifulSoup
from loguru import logger

FUNPAY_BASE = "https://funpay.com"
FUNPAY_GOLDEN_KEY = os.environ.get("FUNPAY_GOLDEN_KEY", "")
TEST_MESSAGE = "Тест отправки сообщения (диагностика)"


async def debug_chat(order_id: str):
    if not FUNPAY_GOLDEN_KEY:
        print("❌ FUNPAY_GOLDEN_KEY не задан в .env")
        sys.exit(1)

    client = httpx.AsyncClient(
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
        },
    )
    cookies = {"golden_key": FUNPAY_GOLDEN_KEY}

    print(f"\n{'='*60}")
    print(f"Диагностика FunPay чата для заказа: {order_id}")
    print(f"{'='*60}\n")

    # ── Шаг 1: Главная страница — получаем CSRF и user_id ────────────────────
    print("Шаг 1: Получаем CSRF токен с главной страницы...")
    resp = await client.get("/", cookies=cookies)
    print(f"  Статус: {resp.status_code}")

    # Сохраняем PHPSESSID
    php_session = ""
    for name, value in resp.cookies.items():
        if name.upper() == "PHPSESSID":
            php_session = value
            cookies["PHPSESSID"] = value
            print(f"  PHPSESSID получен: {value[:10]}...")

    # CSRF
    csrf = ""
    for pattern in [
        r'<meta\s+name=["\']csrf-token["\'][^>]*content=["\']([\w\-]+)',
        r'"csrf_token"\s*:\s*["\']([\w\-]+)',
        r'csrf\s*[:=]\s*["\']([\w\-]+)',
        r'data-csrf=["\']([\w\-]+)',
    ]:
        m = re.search(pattern, resp.text)
        if m:
            csrf = m.group(1)
            print(f"  CSRF токен: {csrf[:20]}...")
            break

    if not csrf:
        print("  ❌ CSRF токен не найден! Проверьте golden_key")
        # Выводим часть HTML для диагностики
        print(f"  HTML (первые 500 символов): {resp.text[:500]}")
        await client.aclose()
        return

    # user_id
    user_id = None
    m = re.search(r'/users/(\d+)/', resp.text)
    if m:
        user_id = m.group(1)
        print(f"  User ID: {user_id}")
    else:
        print("  ⚠️  User ID не найден (golden_key может быть устаревшим)")

    # ── Шаг 2: Страница заказа — ищем chat_id ────────────────────────────────
    print(f"\nШаг 2: Получаем страницу заказа /orders/{order_id}/...")
    resp2 = await client.get(f"/orders/{order_id}/", cookies=cookies)
    print(f"  Статус: {resp2.status_code}")
    print(f"  URL после редиректов: {resp2.url}")

    html = resp2.text

    # Сохраняем HTML для анализа
    html_file = f"/tmp/funpay_order_{order_id}.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML сохранён в {html_file} для ручного анализа")

    # Ищем chat_id всеми способами
    chat_id = None
    search_patterns = [
        (r'data-id=["\'](\d+)["\']', "data-id"),
        (r'data-node=["\'](\d+)["\']', "data-node"),
        (r'data-chat=["\'](\d+)["\']', "data-chat"),
        (r'/chat/\?node=(\d+)', "?node="),
        (r'"nodeId"\s*:\s*(\d+)', "nodeId JS"),
        (r'"node"\s*:\s*(\d+)', "node JS"),
        (r'node_id\s*[:=]\s*["\']?(\d+)', "node_id"),
        (r'chat_id\s*[:=]\s*["\']?(\d+)', "chat_id var"),
        (r'"id"\s*:\s*(\d+)', "id JS"),
    ]

    print("\n  Поиск chat_id на странице заказа:")
    for pattern, label in search_patterns:
        matches = re.findall(pattern, html)
        if matches:
            print(f"    ✓ {label}: {matches[:5]}")
            if chat_id is None:
                chat_id = int(matches[0])
        else:
            print(f"    - {label}: не найден")

    if chat_id:
        print(f"\n  ✅ chat_id определён: {chat_id}")
    else:
        print("\n  ❌ chat_id не найден ни одним способом")

    # Ищем в HTML блоки связанные с чатом
    soup = BeautifulSoup(html, "html.parser")
    print("\n  Элементы с data-* атрибутами (чат/node):")
    for el in soup.find_all(True):
        attrs = el.attrs
        relevant = {k: v for k, v in attrs.items()
                    if any(x in k.lower() for x in ["node", "chat", "id", "message"])}
        if relevant:
            tag_info = f"<{el.name} {relevant}>"
            print(f"    {tag_info[:120]}")

    # ── Шаг 3: Пробуем /runner/ с найденным chat_id ──────────────────────────
    if chat_id:
        print(f"\nШаг 3: Тест отправки через /runner/ (chat_id={chat_id})...")
        payload = {
            "objects": [
                {
                    "type": "chat_message",
                    "data": {
                        "node": chat_id,
                        "last_message": -1,
                        "content": TEST_MESSAGE,
                    },
                }
            ],
            "request": False,
            "csrf_token": csrf,
        }
        headers_runner = {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{FUNPAY_BASE}/orders/{order_id}/",
            "x-csrf-token": csrf,
        }
        resp3 = await client.post(
            "/runner/",
            content=json.dumps(payload),
            cookies=cookies,
            headers=headers_runner,
        )
        print(f"  HTTP статус: {resp3.status_code}")
        print(f"  Ответ (первые 500 символов): {resp3.text[:500]}")
        if resp3.status_code == 200:
            print("  ✅ /runner/ вернул 200")
        else:
            print(f"  ❌ /runner/ вернул {resp3.status_code}")
    else:
        print("\nШаг 3: Пропускаем /runner/ (chat_id не найден)")

    # ── Шаг 4: Пробуем /chat/ endpoint ───────────────────────────────────────
    print(f"\nШаг 4: Тест через /chat/ endpoint...")
    chat_page = await client.get(f"/chat/?node={order_id}", cookies=cookies)
    print(f"  GET /chat/?node={order_id}: HTTP {chat_page.status_code}")
    print(f"  URL: {chat_page.url}")

    # Ищем chat_id на странице чата
    chat_html = chat_page.text
    chat_id_from_chat = None
    for pattern, label in search_patterns:
        m = re.search(pattern, chat_html)
        if m:
            chat_id_from_chat = int(m.group(1))
            print(f"  chat_id из /chat/ страницы ({label}): {chat_id_from_chat}")
            break

    # ── Шаг 5: Пробуем отправить через форму ─────────────────────────────────
    print(f"\nШаг 5: Тест через POST /orders/{order_id}/ (форма)...")
    form_data = {
        "csrf_token": csrf,
        "action": "send_message",
        "order_id": order_id,
        "text": TEST_MESSAGE,
        "message": TEST_MESSAGE,
    }
    headers_form = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{FUNPAY_BASE}/orders/{order_id}/",
        "x-csrf-token": csrf,
    }
    resp5 = await client.post(
        f"/orders/{order_id}/",
        data=form_data,
        cookies=cookies,
        headers=headers_form,
    )
    print(f"  HTTP статус: {resp5.status_code}")
    print(f"  Ответ (первые 500 символов): {resp5.text[:500]}")

    # ── Шаг 6: Ищем форму чата в HTML заказа ─────────────────────────────────
    print(f"\nШаг 6: Анализ формы чата в HTML заказа...")
    forms = soup.find_all("form")
    print(f"  Найдено форм: {len(forms)}")
    for i, form in enumerate(forms):
        action = form.get("action", "")
        method = form.get("method", "get")
        inputs = [(inp.get("name", ""), inp.get("type", ""), inp.get("value", ""))
                  for inp in form.find_all("input")]
        print(f"  Форма #{i+1}: action='{action}', method='{method}', inputs={inputs}")

    # ── Итог ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("ИТОГ ДИАГНОСТИКИ:")
    print(f"  order_id: {order_id}")
    print(f"  user_id:  {user_id}")
    print(f"  csrf:     {csrf[:20]}..." if csrf else "  csrf:     НЕ НАЙДЕН")
    print(f"  chat_id:  {chat_id}" if chat_id else "  chat_id:  НЕ НАЙДЕН")
    print(f"\nДля ручного анализа HTML: cat {html_file} | grep -i 'node\\|chat\\|message'")
    print(f"{'='*60}\n")

    await client.aclose()


if __name__ == "__main__":
    order_id = sys.argv[1] if len(sys.argv) > 1 else "ZVWPQ96F"

    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG")

    asyncio.run(debug_chat(order_id))
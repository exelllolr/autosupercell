"""
Находит node заказа и пробует отправить тестовое сообщение разными способами.

python examples/funpay_test_send.py HHPXAGJ9
"""
import asyncio
import os
import re
import sys
import json
import string
import random
from pathlib import Path
from html import unescape
from dotenv import load_dotenv

load_dotenv("/root/autosupercell/.env")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import httpx

FUNPAY_BASE = "https://funpay.com"
FUNPAY_GOLDEN_KEY = os.environ.get("FUNPAY_GOLDEN_KEY", "")


def _tag():
    return "".join(random.choices(string.digits + "abcdef", k=8))


async def test_send(order_id: str):
    if not FUNPAY_GOLDEN_KEY:
        print("❌ FUNPAY_GOLDEN_KEY не задан")
        return

    client = httpx.AsyncClient(
        base_url=FUNPAY_BASE, timeout=30.0, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 Chrome/146.0.0.0"},
    )

    # ── 1. Получаем CSRF и PHPSESSID ─────────────────────────────────────────
    print("Шаг 1: GET / (CSRF + PHPSESSID)...")
    resp = await client.get("/", cookies={"golden_key": FUNPAY_GOLDEN_KEY})
    cookies = {"golden_key": FUNPAY_GOLDEN_KEY}
    for name, value in resp.cookies.items():
        if name.upper() == "PHPSESSID":
            cookies["PHPSESSID"] = value
            print(f"  PHPSESSID: {value[:15]}...")

    # CSRF из data-app-data
    csrf = ""
    m = re.search(r'<body[^>]+data-app-data=["\']([^"\']+)["\']', resp.text)
    if m:
        try:
            data = json.loads(unescape(m.group(1)))
            csrf = data.get("csrf-token", "")
            user_id = data.get("userId", 0)
            print(f"  CSRF: {csrf}")
            print(f"  userId: {user_id}")
        except Exception as e:
            print(f"  ❌ JSON parse error: {e}")
    else:
        print("  ❌ data-app-data не найден!")
        return

    # ── 2. Получаем страницу заказа и ищем node ───────────────────────────────
    print(f"\nШаг 2: GET /orders/{order_id}/ (ищем node)...")
    order_resp = await client.get(f"/orders/{order_id}/", cookies=cookies)
    print(f"  HTTP {order_resp.status_code}")

    html = order_resp.text
    with open(f"/tmp/funpay_order_{order_id}.html", "w") as f:
        f.write(html)
    print(f"  HTML сохранён: /tmp/funpay_order_{order_id}.html")

    # Все паттерны поиска node
    print("\n  Поиск node в HTML:")
    node = None
    patterns = [
        (r'data-node=["\'](\d+)["\']', "data-node"),
        (r'data-id=["\'](\d+)["\']', "data-id"),
        (r'href=["\'][^"\']*chat[^"\']*node=(\d+)', "href chat node"),
        (r'/chat/\?node=(\d+)', "?node="),
        (r'"node"\s*:\s*(\d+)', '"node":'),
        (r'"nodeId"\s*:\s*(\d+)', '"nodeId":'),
        (r'data-chat=["\'](\d+)["\']', "data-chat"),
        (r'"chatNode"\s*:\s*(\d+)', '"chatNode":'),
        (r'node_id["\s:=]+(\d+)', "node_id"),
    ]
    for pattern, label in patterns:
        matches = re.findall(pattern, html)
        if matches:
            print(f"    ✓ {label}: {matches[:5]}")
            if node is None:
                node = int(matches[0])
        else:
            print(f"    - {label}: нет")

    # data-app-data на странице заказа
    m2 = re.search(r'<body[^>]+data-app-data=["\']([^"\']+)["\']', html)
    if m2:
        try:
            order_data = json.loads(unescape(m2.group(1)))
            print(f"\n  data-app-data на странице заказа: {order_data}")
            for key in ["node", "nodeId", "chatNode", "chatId"]:
                if key in order_data:
                    node = int(order_data[key])
                    print(f"  ✓ node из data-app-data[{key}]: {node}")
        except Exception as e:
            print(f"  Ошибка парсинга data-app-data заказа: {e}")

    print(f"\n  Итоговый node: {node}")

    if node is None:
        print("\n❌ node не найден — смотри /tmp/funpay_order_*.html вручную")
        print("Команда: grep -i 'node\\|chat' /tmp/funpay_order_" + order_id + ".html | head -30")
        await client.aclose()
        return

    # ── 3. Пробуем отправить сообщение ────────────────────────────────────────
    test_text = "Тест отправки (диагностика)"
    print(f"\nШаг 3: Отправка тестового сообщения (node={node})...")

    # Вариант А: с id=str(node)
    for variant_name, objects in [
        ("id=str(node)", [{"type": "chat_message", "id": str(node), "tag": _tag(),
                           "data": {"node": node, "last_message": -1, "content": test_text}}]),
        ("id=order_id",  [{"type": "chat_message", "id": order_id, "tag": _tag(),
                           "data": {"node": node, "last_message": -1, "content": test_text}}]),
        ("без id",       [{"type": "chat_message", "tag": _tag(),
                           "data": {"node": node, "last_message": -1, "content": test_text}}]),
    ]:
        payload = {
            "objects": json.dumps(objects, ensure_ascii=False),
            "request": "false",
            "csrf_token": csrf,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "Referer": f"{FUNPAY_BASE}/orders/{order_id}/",
        }
        r = await client.post("/runner/", data=payload, cookies=cookies, headers=headers)
        print(f"\n  Вариант [{variant_name}]:")
        print(f"    HTTP: {r.status_code}")
        print(f"    objects отправлено: {json.dumps(objects, ensure_ascii=False)[:200]}")
        print(f"    Ответ: {r.text[:400]}")

        # Проверяем успех
        try:
            resp_data = r.json()
            objs = resp_data.get("objects", [])
            has_msg = any(o.get("type") == "chat_message" for o in objs)
            response_val = resp_data.get("response")
            print(f"    chat_message в ответе: {has_msg}")
            print(f"    response: {response_val}")
            if has_msg:
                print(f"    ✅ УСПЕХ — этот вариант работает!")
                break
        except Exception:
            pass

    await client.aclose()
    print("\nГотово. Проверь чат заказа на funpay.com")


if __name__ == "__main__":
    order_id = sys.argv[1] if len(sys.argv) > 1 else "HHPXAGJ9"
    asyncio.run(test_send(order_id))
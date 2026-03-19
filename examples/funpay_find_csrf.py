"""
Находит CSRF в реальном HTML FunPay и показывает строки где он встречается.

python examples/funpay_find_csrf.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("/root/autosupercell/.env")

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import httpx

FUNPAY_GOLDEN_KEY = os.environ.get("FUNPAY_GOLDEN_KEY", "")
FUNPAY_BASE = "https://funpay.com"


async def find_csrf():
    if not FUNPAY_GOLDEN_KEY:
        print("❌ FUNPAY_GOLDEN_KEY не задан")
        return

    client = httpx.AsyncClient(
        base_url=FUNPAY_BASE,
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0.0.0"},
    )
    cookies = {"golden_key": FUNPAY_GOLDEN_KEY}

    print("GET https://funpay.com/ ...")
    resp = await client.get("/", cookies=cookies)
    print(f"HTTP {resp.status_code}")

    # Сохраняем PHPSESSID
    phpsessid = ""
    for name, value in resp.cookies.items():
        if name.upper() == "PHPSESSID":
            phpsessid = value
            cookies["PHPSESSID"] = value
    print(f"PHPSESSID: {phpsessid[:15]}..." if phpsessid else "PHPSESSID: НЕТ")

    html = resp.text

    # Сохраняем HTML
    path = "/tmp/funpay_main.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML сохранён: {path}")
    print()

    # Ищем все строки содержащие "csrf" (регистронезависимо)
    print("=== Строки с 'csrf' в HTML ===")
    lines = html.split("\n")
    found = 0
    for i, line in enumerate(lines):
        if "csrf" in line.lower():
            print(f"  Строка {i+1}: {line.strip()[:200]}")
            found += 1
    if found == 0:
        print("  ❌ Слово 'csrf' не найдено в HTML!")
    print()

    # Ищем все строки содержащие "app." (JS переменные FunPay)
    print("=== JS переменные app.* ===")
    for i, line in enumerate(lines):
        if re.search(r'\bapp\.\w+\s*=', line):
            print(f"  Строка {i+1}: {line.strip()[:200]}")
    print()

    # Ищем hex строки 32+ символов (возможный CSRF)
    print("=== Hex строки 32+ символов (возможный CSRF) ===")
    hex_matches = re.findall(r'["\']([a-f0-9]{32,})["\']', html)
    for h in hex_matches[:10]:
        print(f"  {h}")
    print()

    # Теперь делаем /runner/ запрос и смотрим полный ответ
    print("=== POST /runner/ init ответ ===")
    import json, random, string
    tag = "".join(random.choices(string.digits + "abcdef", k=8))
    objects = [{"type": "orders_counters", "id": "0", "tag": tag, "data": False}]
    runner_resp = await client.post(
        "/runner/",
        data={"objects": json.dumps(objects), "request": "false", "csrf_token": ""},
        cookies=cookies,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    print(f"HTTP {runner_resp.status_code}")
    print(f"Полный ответ: {runner_resp.text[:1000]}")
    print()

    # Ищем CSRF в JS файлах (FunPay может передавать его через JS bundle)
    print("=== Ищем CSRF в JS src тегах ===")
    js_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
    for src in js_srcs[:5]:
        print(f"  {src}")

    await client.aclose()


asyncio.run(find_csrf())
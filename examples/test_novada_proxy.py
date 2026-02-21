"""
Тест подключения к Novada API (прокси).

Критерии подключения Novada:
- NOVADA_USERNAME — имя пользователя из личного кабинета (Dashboard → API Key)
- NOVADA_API_KEY — API key (используется как пароль прокси)
- Сервер: super.novada.pro:7777 (официальный из документации)
- Формат username: USERNAME-zone-res-region-us (residential, US) или USERNAME-zone-dcp (datacenter)

Запуск:
  set NOVADA_ENABLED=true
  set NOVADA_USERNAME=novada_acc4c5bf5f5
  set NOVADA_API_KEY=622f142f1bf74ffe8d359fb8dc0815d1
  python examples/test_novada_proxy.py

Или задать переменные в .env и включить NOVADA_ENABLED=true, PROXY_ENABLED=true.
"""

import os
import sys
from pathlib import Path

# Подгружаем .env если есть
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _novada_server():
    return os.environ.get("NOVADA_PROXY_HOST", "super.novada.pro").strip() or "super.novada.pro"


def _novada_port():
    try:
        return int(os.environ.get("NOVADA_PROXY_PORT", "7777"))
    except ValueError:
        return 7777


TEST_URL_IPINFO = "http://ipinfo.novada.pro"  # Официальный тест Novada
TEST_URL_EXT = "https://api.ipify.org?format=json"


def get_novada_proxy_url() -> str:
    """Собрать URL прокси из переменных окружения."""
    user = os.environ.get("NOVADA_USERNAME", "").strip()
    key = os.environ.get("NOVADA_API_KEY", "").strip()
    zone = os.environ.get("NOVADA_ZONE", "res").strip() or "res"
    region = os.environ.get("NOVADA_REGION", "").strip()
    if not user or not key:
        return ""
    username_part = f"{user}-zone-{zone}"
    if region:
        username_part += f"-region-{region.lower()}"
    server = _novada_server()
    port = _novada_port()
    return f"http://{username_part}:{key}@{server}:{port}"


def main():
    print("=" * 60)
    print("Novada API — проверка подключения прокси")
    print("=" * 60)

    user = os.environ.get("NOVADA_USERNAME", "").strip()
    key = os.environ.get("NOVADA_API_KEY", "").strip()
    enabled = os.environ.get("NOVADA_ENABLED", "false").lower() in ("true", "1", "yes")

    print(f"\nNOVADA_USERNAME: {user or '(не задан)'}")
    print(f"NOVADA_API_KEY:  {'*' * 8}{key[-4:] if key else '(не задан)'}")
    print(f"NOVADA_ENABLED:  {enabled}")

    if not user or not key:
        print("\nОшибка: задайте NOVADA_USERNAME и NOVADA_API_KEY в .env или в окружении.")
        print("Пример в .env:")
        print("  NOVADA_ENABLED=true")
        print("  NOVADA_USERNAME=novada_acc4c5bf5f5")
        print("  NOVADA_API_KEY=622f142f1bf74ffe8d359fb8dc0815d1")
        print("  NOVADA_ZONE=res")
        print("  NOVADA_REGION=us")
        sys.exit(1)

    proxy_url = get_novada_proxy_url()
    proxies = {"http": proxy_url, "https": proxy_url}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

    NOVADA_SERVER = _novada_server()
    NOVADA_PORT = _novada_port()
    print(f"\nСервер: {NOVADA_SERVER}:{NOVADA_PORT}")
    print(f"Username (формат): {user}-zone-res-region-us (или zone-dcp для datacenter)")

    # Тест 1: ipinfo.novada.pro (официальный тест Novada)
    print("\n--- Тест 1: ipinfo.novada.pro ---")
    try:
        r = requests.get(TEST_URL_IPINFO, proxies=proxies, timeout=30, headers=headers, verify=False)
        if r.status_code == 200:
            print("OK", r.status_code)
            print("Ответ (IP/инфо):", r.text[:500] if r.text else "(пусто)")
        else:
            print("Ошибка:", r.status_code, r.text[:200])
    except Exception as e:
        print("Ошибка запроса:", e)

    # Тест 2: внешний IP через прокси
    print("\n--- Тест 2: api.ipify.org (внешний IP) ---")
    try:
        r = requests.get(TEST_URL_EXT, proxies=proxies, timeout=30, headers=headers, verify=False)
        if r.status_code == 200:
            print("OK", r.status_code)
            data = r.json()
            print("IP через прокси:", data.get("ip", "?"))
        else:
            print("Ошибка:", r.status_code)
    except Exception as e:
        print("Ошибка запроса:", e)

    # Тест 3: store.supercell.com (доступность магазина)
    print("\n--- Тест 3: store.supercell.com ---")
    try:
        r = requests.get(
            "https://store.supercell.com",
            proxies=proxies,
            timeout=25,
            headers=headers,
            verify=False,
        )
        if r.status_code == 200:
            print("OK", r.status_code, "— магазин доступен через прокси")
        else:
            print("Ответ:", r.status_code)
    except Exception as e:
        print("Ошибка запроса:", e)

    print("\n" + "=" * 60)
    print("Что ещё нужно для подключения:")
    print("1. В .env: PROXY_ENABLED=true и NOVADA_ENABLED=true")
    print("2. В личном кабинете Novada: проверить баланс и активную подписку на прокси")
    print("3. Endpoint Generator в Dashboard: при необходимости взять точный host:port")
    print("4. Документация: https://developer.novada.com/")
    print("=" * 60)


if __name__ == "__main__":
    main()

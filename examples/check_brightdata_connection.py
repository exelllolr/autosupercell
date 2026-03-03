"""
Проверка подключения к Bright Data без зависимостей приложения.
Запуск: python examples/check_brightdata_connection.py
Нужен только: pip install requests
"""
import os
import sys
from pathlib import Path

# Загружаем .env вручную (без python-dotenv)
root = Path(__file__).resolve().parent.parent
env_file = root / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and value and not key in os.environ:
                os.environ[key] = value

try:
    import requests
except ImportError:
    print("Установите requests: pip install requests")
    sys.exit(1)

# Параметры из .env
PROXY_ENABLED = os.environ.get("PROXY_ENABLED", "").lower() in ("1", "true", "yes")
BRIGHTDATA_ENABLED = os.environ.get("BRIGHTDATA_ENABLED", "").lower() in ("1", "true", "yes")
BRIGHTDATA_HOST = os.environ.get("BRIGHTDATA_HOST", "brd.superproxy.io").strip()
BRIGHTDATA_PORT = os.environ.get("BRIGHTDATA_PORT", "33335").strip()
BRIGHTDATA_USERNAME = (os.environ.get("BRIGHTDATA_USERNAME", "") or "").strip()
BRIGHTDATA_API_KEY = (os.environ.get("BRIGHTDATA_API_KEY", "") or "").strip()
BRIGHTDATA_PASSWORD = (os.environ.get("BRIGHTDATA_PASSWORD", "") or "").strip()
password = BRIGHTDATA_API_KEY or BRIGHTDATA_PASSWORD

def main():
    print("=" * 60)
    print("Проверка подключения к Bright Data")
    print("=" * 60)
    print(f"PROXY_ENABLED:      {PROXY_ENABLED}")
    print(f"BRIGHTDATA_ENABLED: {BRIGHTDATA_ENABLED}")
    print(f"BRIGHTDATA_HOST:    {BRIGHTDATA_HOST}")
    print(f"BRIGHTDATA_PORT:   {BRIGHTDATA_PORT}")
    print(f"BRIGHTDATA_USERNAME: {BRIGHTDATA_USERNAME or '(не задан)'}")
    print(f"Аутентификация:    {'API ключ' if BRIGHTDATA_API_KEY else 'пароль'} ({'(задана)' if password else 'НЕ ЗАДАНА!'})")
    print()

    if not BRIGHTDATA_ENABLED or not BRIGHTDATA_USERNAME:
        print("Ошибка: BRIGHTDATA_ENABLED и BRIGHTDATA_USERNAME должны быть заданы в .env")
        return 1
    if not password:
        print("Ошибка: задайте BRIGHTDATA_API_KEY или BRIGHTDATA_PASSWORD в .env")
        return 1

    proxy_url = f"http://{BRIGHTDATA_USERNAME}:{password}@{BRIGHTDATA_HOST}:{BRIGHTDATA_PORT}"
    proxies = {"http": proxy_url, "https": proxy_url}

    # Тест 1: Bright Data welcome (проверка гео)
    print("Тест 1: Bright Data geo.brdtest.com...")
    try:
        r = requests.get(
            "https://geo.brdtest.com/welcome.txt?product=resi&method=native",
            proxies=proxies,
            timeout=30,
            verify=False,
        )
        if r.status_code == 200:
            print("  OK — подключение к Bright Data работает")
            for line in r.text.strip().split("\n"):
                if ":" in line:
                    print(f"  {line.strip()}")
        else:
            print(f"  Ошибка HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        err = str(e)
        print(f"  Ошибка: {e}")
        if "407" in err or "Auth failed" in err:
            print("  Подсказка: 407 = неверный логин/пароль прокси. В кабинете Bright Data проверьте:")
            print("    - Zone → Proxy credentials: Username и Password (или API key для прокси).")
            print("    - BRIGHTDATA_API_KEY в .env — это ключ для прокси-аутентификации, не путать с API для HTTP API.")
        return 1

    # Тест 2: store.supercell.com
    print("\nТест 2: store.supercell.com...")
    try:
        r = requests.get(
            "https://store.supercell.com",
            proxies=proxies,
            timeout=30,
            verify=False,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        print(f"  HTTP {r.status_code}, размер ответа: {len(r.content)} байт")
        if r.status_code == 200:
            print("  OK — Store доступен через прокси")
        else:
            print("  Проверьте ответ (редирект или блок возможны)")
    except Exception as e:
        print(f"  Ошибка: {e}")
        return 1

    print("\n" + "=" * 60)
    print("Проверка завершена.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    sys.exit(main())

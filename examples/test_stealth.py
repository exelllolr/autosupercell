"""
Тест stealth настроек браузера.
Открывает bot.sannysoft.com и делает скриншот — показывает что детектируется.

Запуск:
  1. python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  2. python examples/test_stealth.py
"""

import requests
import sys
import time

API_URL = "http://127.0.0.1:8000/api/v1"


def check_server():
    try:
        r = requests.get(f"{API_URL}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def main():
    print("=" * 60)
    print("ТЕСТ STEALTH БРАУЗЕРА")
    print("Проверяем bot.sannysoft.com и fingerprintjs.com")
    print("=" * 60)

    if not check_server():
        print("[ERR] Сервер недоступен. Запусти:")
        print("  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
        sys.exit(1)

    print("\n[>] Запрашиваем тест stealth через API...")
    try:
        r = requests.post(
            f"{API_URL}/supercell/test-stealth",
            json={},
            timeout=120,
        )
        if r.status_code == 200:
            data = r.json()
            print("\n[OK] Тест завершён!")
            print(f"    Скриншот sannysoft: {data.get('screenshot_sannysoft')}")
            print(f"    Скриншот fingerprint: {data.get('screenshot_fingerprint')}")
            results = data.get("results", {})
            if results:
                print("\n    Результаты детекции:")
                for k, v in results.items():
                    status = "[PASS]" if not v else "[FAIL]"
                    print(f"      {status} {k}: {v}")
        else:
            print(f"[ERR] {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[ERR] {e}")
        print("\nЕсли endpoint /test-stealth не существует, запусти вручную:")
        print("  python examples/test_stealth_direct.py")


if __name__ == "__main__":
    main()

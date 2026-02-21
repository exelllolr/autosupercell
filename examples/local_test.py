"""
Локальный тест авторизации Supercell без Docker.
Запускать с включённым VPN на ПК.

Запуск:
  1. Убедись что VPN включён
  2. python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  3. В другом терминале: python examples/local_test.py
"""

import requests
import sys

API_URL = "http://127.0.0.1:8000/api/v1"
TIMEOUT = 600  # 10 минут


def check_server():
    try:
        r = requests.get(f"{API_URL}/health", timeout=5)
        if r.status_code == 200:
            print("[OK] Сервер доступен")
            return True
    except Exception as e:
        print(f"[ERR] Сервер недоступен: {e}")
        print("Запусти сервер: python -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
        return False


def main():
    print("=" * 60)
    print("ЛОКАЛЬНЫЙ ТЕСТ АВТОРИЗАЦИИ SUPERCELL")
    print("Режим: headed браузер + VPN (без прокси)")
    print("=" * 60)

    if not check_server():
        sys.exit(1)

    email = input("\nEmail Supercell аккаунта: ").strip()
    code = input("Код верификации из письма (или Enter — ввести вручную в браузере): ").strip() or None

    if code:
        code = code.replace(" ", "").replace("-", "")

    print(f"\n[>] Запускаем авторизацию для {email}...")
    print("    Браузер откроется на экране — это нормально (headed режим)")
    if not code:
        print("    У тебя будет 2 минуты чтобы ввести код в браузере вручную")
    print()

    payload = {"email": email}
    if code:
        payload["verification_code"] = code

    try:
        r = requests.post(f"{API_URL}/supercell/login", json=payload, timeout=TIMEOUT)
        data = r.json()

        if r.status_code == 200:
            if data.get("authenticated"):
                print("[OK] Авторизация УСПЕШНА!")
                print(f"    URL: {data.get('url')}")
                print(f"    Скриншот: {data.get('screenshot')}")
                if data.get("video"):
                    print(f"    Видео: {data.get('video')}")
            else:
                print("[WARN] Авторизация не подтверждена")
                print(f"    Сообщение: {data.get('message', '')[:200]}")
                print(f"    Скриншот: {data.get('screenshot')}")
        else:
            err = data.get("detail", {})
            if isinstance(err, dict):
                print(f"[ERR] {err.get('error', 'Неизвестная ошибка')[:300]}")
                if err.get("screenshot"):
                    print(f"    Скриншот: {err['screenshot']}")
            else:
                print(f"[ERR] {err}")

    except requests.exceptions.Timeout:
        print("[ERR] Таймаут 10 минут — сервер не ответил")
    except Exception as e:
        print(f"[ERR] {e}")


if __name__ == "__main__":
    main()

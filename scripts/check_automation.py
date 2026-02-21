#!/usr/bin/env python3
"""
Проверка автоматизации AutoSupercell.

Запуск (API должен быть доступен на http://localhost:8000):
  python scripts/check_automation.py

Или с указанием хоста:
  python scripts/check_automation.py --base-url http://127.0.0.1:8000
"""

import argparse
import json
import sys

try:
    import requests
except ImportError:
    print("Установите requests: pip install requests")
    sys.exit(1)

DEFAULT_BASE = "http://localhost:8000"
TIMEOUT = 10
ORDER_TIMEOUT = 15


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def check_automation(base_url: str) -> bool:
    base = base_url.rstrip("/")
    api = f"{base}/api/v1"
    all_ok = True

    print("=" * 60)
    print("Проверка автоматизации AutoSupercell")
    print("=" * 60)
    print(f"Base URL: {base}\n")

    # 1. Корень и health
    print("1. Доступность API")
    try:
        r = requests.get(f"{base}/", timeout=TIMEOUT)
        if r.status_code == 200:
            ok(f"GET / -> {r.status_code}")
            data = r.json()
            print(f"     Сервис: {data.get('service', '?')}, version: {data.get('version', '?')}")
        else:
            fail(f"GET / -> {r.status_code}")
            all_ok = False
    except requests.exceptions.RequestException as e:
        fail(f"API недоступен: {e}")
        print("\n   Запустите API (локально или Docker):")
        print("   Локально: uvicorn app.main:app --host 0.0.0.0 --port 8000")
        print("   Docker:   docker compose up -d")
        return False

    try:
        r = requests.get(f"{api}/health", timeout=TIMEOUT)
        if r.status_code == 200:
            ok(f"GET /api/v1/health -> {r.status_code}")
        else:
            fail(f"GET /api/v1/health -> {r.status_code}")
            all_ok = False
    except requests.exceptions.RequestException as e:
        fail(f"Health check: {e}")
        all_ok = False

    # 2. Список маршрутов (наличие автоматизации)
    print("\n2. Маршруты автоматизации")
    try:
        r = requests.get(f"{base}/api/v1/routes", timeout=TIMEOUT)
        if r.status_code != 200:
            fail(f"GET /api/v1/routes -> {r.status_code}")
            all_ok = False
        else:
            data = r.json()
            routes = [x.get("path", "") for x in data.get("routes", [])]
            need = ["/api/v1/health", "/api/v1/orders/process", "/api/v1/supercell/purchase"]
            for path in need:
                if path in routes or any(path in r for r in routes):
                    ok(f"Есть: {path}")
                else:
                    warn(f"Не найден: {path}")
    except requests.exceptions.RequestException as e:
        fail(f"Список маршрутов: {e}")
        all_ok = False

    # 3. Очередь заказов (orders/process) — нужны Redis и worker
    print("\n3. Очередь заказов (Redis + Worker)")
    order_payload = {
        "order_id": "check_auto_001",
        "product_name": "Test Gems",
        "product_type": "gems",
        "game": "clash-royale",
        "amount": 4.99,
        "currency": "USD",
        "user_account": "check@test.local",
        "payment_method": "google_pay",
        "card_info": {"last4": "0000", "card_id": "test"},
    }
    try:
        r = requests.post(
            f"{api}/orders/process",
            json=order_payload,
            headers={"Content-Type": "application/json"},
            timeout=ORDER_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            ok(f"POST /api/v1/orders/process -> {r.status_code}")
            print(f"     job_id: {data.get('job_id', '?')}, status: {data.get('status', '?')}")
        else:
            try:
                err = r.json()
                detail = err.get("detail", r.text[:200])
            except Exception:
                detail = r.text[:200]
            warn(f"POST /api/v1/orders/process -> {r.status_code}: {detail}")
            if r.status_code == 500 and "redis" in str(detail).lower():
                print("     Убедитесь, что Redis запущен и worker поднят (docker compose up -d)")
    except requests.exceptions.RequestException as e:
        warn(f"Очередь заказов: {e}")
        print("     Redis/Worker могут быть не запущены.")

    # 4. Метрики
    print("\n4. Метрики Prometheus")
    try:
        r = requests.get(f"{base}/metrics", timeout=TIMEOUT)
        if r.status_code == 200:
            ok("GET /metrics доступен")
        else:
            warn(f"GET /metrics -> {r.status_code}")
    except requests.exceptions.RequestException as e:
        warn(f"Метрики: {e}")

    # Итог и подсказки
    print("\n" + "=" * 60)
    if all_ok:
        print("Итог: базовая проверка пройдена.")
    else:
        print("Итог: есть проблемы (см. выше).")

    print("\nПроверка полной автоматизации (браузер + покупка):")
    print("  python examples/purchase_demo.py")
    print("  (требуется email Supercell и код верификации или пароль от почты)")
    print("=" * 60)
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Проверка автоматизации AutoSupercell")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE,
        help=f"Base URL API (по умолчанию {DEFAULT_BASE})",
    )
    args = parser.parse_args()
    success = check_automation(args.base_url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

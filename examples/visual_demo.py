"""Визуальная демонстрация авторизации и привязки Google Pay."""

import requests
import json
import time
from pathlib import Path

API_URL = "http://localhost:8000/api/v1"


def print_step(step_num: int, title: str, description: str):
    """Вывести информацию о шаге."""
    print(f"\n{'='*60}")
    print(f"ШАГ {step_num}: {title}")
    print(f"{'='*60}")
    print(description)
    print()


def demo_google_login(email: str, password: str = None):
    """Демонстрация авторизации в Google."""
    print_step(
        1,
        "Авторизация в Google аккаунте",
        f"Email: {email}\nПроцесс: Открытие браузера → Вход в Google → Проверка авторизации",
    )

    data = {"email": email, "use_existing_session": False}
    if password:
        data["password"] = password

    print("📤 Отправка запроса...")
    response = requests.post(f"{API_URL}/auth/google/login", json=data, timeout=120)

    if response.status_code == 200:
        result = response.json()
        print("✅ Авторизация успешна!")
        print(f"   Session ID: {result.get('session_id')}")
        print(f"   Скриншот: {result.get('screenshot')}")
        print(f"   Статус: {result.get('message')}")
        return result
    else:
        print(f"❌ Ошибка: {response.status_code}")
        print(response.text)
        return None


def demo_add_card(email: str, card_data: dict):
    """Демонстрация привязки карты к Google Pay."""
    print_step(
        2,
        "Привязка карты к Google Pay",
        f"Email: {email}\nКарта: •••• {card_data['card_number'][-4:]}\nПроцесс: Открытие Google Pay → Добавление карты → Сохранение",
    )

    print("📤 Отправка запроса...")
    response = requests.post(
        f"{API_URL}/auth/google/pay/add-card", json=card_data, timeout=120
    )

    if response.status_code == 200:
        result = response.json()
        print("✅ Карта успешно привязана!")
        print(f"   Last4: {result.get('card_last4')}")
        print(f"   Скриншоты: {len(result.get('screenshots', []))} шт.")
        for i, screenshot in enumerate(result.get("screenshots", []), 1):
            print(f"      {i}. {screenshot}")
        return result
    else:
        print(f"❌ Ошибка: {response.status_code}")
        print(response.text)
        return None


def demo_list_cards(email: str):
    """Демонстрация просмотра списка карт."""
    print_step(
        3,
        "Просмотр списка карт в Google Pay",
        f"Email: {email}\nПроцесс: Открытие Google Pay → Извлечение списка карт",
    )

    print("📤 Отправка запроса...")
    response = requests.get(f"{API_URL}/auth/google/pay/cards", params={"email": email}, timeout=120)

    if response.status_code == 200:
        result = response.json()
        print("✅ Список карт получен!")
        print(f"   Найдено карт: {len(result.get('cards', []))}")
        for i, card in enumerate(result.get("cards", []), 1):
            print(f"      {i}. •••• {card.get('last4')} - {card.get('text', '')[:50]}")
        print(f"   Скриншот: {result.get('screenshot')}")
        return result
    else:
        print(f"❌ Ошибка: {response.status_code}")
        print(response.text)
        return None


def demo_create_order(email: str, card_last4: str):
    """Демонстрация создания заказа."""
    print_step(
        4,
        "Создание заказа на покупку",
        f"Email: {email}\nКарта: •••• {card_last4}\nПроцесс: Постановка заказа в очередь → Обработка",
    )

    order_data = {
        "order_id": f"demo_order_{int(time.time())}",
        "product_name": "500 Gems",
        "product_type": "gems",
        "game": "clash-royale",
        "amount": 4.99,
        "currency": "USD",
        "user_account": email,
        "payment_method": "google_pay",
        "card_info": {"last4": card_last4},
    }

    print("📤 Отправка запроса...")
    response = requests.post(f"{API_URL}/orders/process", json=order_data, timeout=30)

    if response.status_code == 200:
        result = response.json()
        print("✅ Заказ создан!")
        print(f"   Order ID: {result.get('order_id')}")
        print(f"   Job ID: {result.get('job_id')}")
        print(f"   Статус: {result.get('status')}")
        return result
    else:
        print(f"❌ Ошибка: {response.status_code}")
        print(response.text)
        return None


def main():
    """Главная функция демонстрации."""
    print("\n" + "="*60)
    print("🎬 ВИЗУАЛЬНАЯ ДЕМОНСТРАЦИЯ")
    print("   Авторизация и привязка Google Pay")
    print("="*60)

    # Проверка доступности API
    try:
        health = requests.get(f"{API_URL}/health", timeout=5)
        if health.status_code != 200:
            print("❌ API сервер недоступен")
            return
    except Exception as e:
        print(f"❌ Ошибка подключения к API: {e}")
        print("Убедитесь, что сервер запущен: docker-compose up -d")
        return

    print("✅ API сервер доступен\n")

    # Данные для демонстрации (замените на свои)
    email = input("Введите email для тестирования: ").strip()
    if not email:
        email = "test@example.com"
        print(f"Используется тестовый email: {email}")

    password = input("Введите пароль (опционально, Enter для пропуска): ").strip()
    if not password:
        password = None
        print("Пароль не указан, будет использована существующая сессия")

    # Шаг 1: Авторизация
    login_result = demo_google_login(email, password)
    if not login_result:
        print("\n❌ Не удалось авторизоваться. Продолжение невозможно.")
        return

    time.sleep(2)

    # Шаг 2: Привязка карты
    card_data = {
        "email": email,
        "card_number": input("\nВведите номер карты (тестовый: 4111111111111111): ").strip() or "4111111111111111",
        "card_exp_month": int(input("Месяц истечения (1-12): ").strip() or "12"),
        "card_exp_year": int(input("Год истечения (например, 2025): ").strip() or "2025"),
    }

    card_result = demo_add_card(email, card_data)
    if not card_result:
        print("\n⚠️  Не удалось привязать карту, но продолжаем...")
        card_last4 = card_data["card_number"][-4:]
    else:
        card_last4 = card_result.get("card_last4", card_data["card_number"][-4:])

    time.sleep(2)

    # Шаг 3: Просмотр карт
    demo_list_cards(email)

    time.sleep(2)

    # Шаг 4: Создание заказа
    order_result = demo_create_order(email, card_last4)

    # Итоги
    print("\n" + "="*60)
    print("📊 ИТОГИ ДЕМОНСТРАЦИИ")
    print("="*60)
    print(f"✅ Авторизация: {'Успешно' if login_result else 'Ошибка'}")
    print(f"✅ Привязка карты: {'Успешно' if card_result else 'Ошибка'}")
    print(f"✅ Создание заказа: {'Успешно' if order_result else 'Ошибка'}")

    # Сохранение результатов
    results = {
        "login": login_result,
        "card": card_result,
        "order": order_result,
    }

    results_file = Path("demo_results.json")
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Результаты сохранены в {results_file}")
    print("\n📸 Скриншоты доступны в директории screenshots/")
    print("   Используйте команду: ls screenshots/")


if __name__ == "__main__":
    main()

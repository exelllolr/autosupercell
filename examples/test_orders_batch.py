"""Пакетное создание тестовых заказов для первых 5 пользователей."""

import requests
import json
import time
from typing import List, Dict

API_URL = "http://localhost:8000/api/v1"


def create_test_order(order_data: Dict) -> Dict:
    """Создать тестовый заказ."""
    try:
        response = requests.post(
            f"{API_URL}/orders/process",
            json=order_data,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка создания заказа {order_data.get('order_id')}: {e}")
        return {"error": str(e)}


def main():
    """Создать тестовые заказы для первых 5 пользователей."""
    
    # Тестовые заказы для первых 5 пользователей
    test_orders = [
        {
            "order_id": "user1_test_001",
            "product_name": "500 Gems",
            "product_type": "gems",
            "game": "clash-royale",
            "amount": 4.99,
            "currency": "USD",
            "user_account": "user1@test.com",
            "payment_method": "google_pay",
            "card_info": {
                "last4": "1234",
                "card_id": "card_user1"
            },
        },
        {
            "order_id": "user2_test_001",
            "product_name": "1000 Gems",
            "product_type": "gems",
            "game": "clash-royale",
            "amount": 9.99,
            "currency": "USD",
            "user_account": "user2@test.com",
            "payment_method": "google_pay",
            "card_info": {
                "last4": "5678",
                "card_id": "card_user2"
            },
        },
        {
            "order_id": "user3_test_001",
            "product_name": "500 Gems",
            "product_type": "gems",
            "game": "brawl-stars",
            "amount": 4.99,
            "currency": "USD",
            "user_account": "user3@test.com",
            "payment_method": "google_pay",
            "card_info": {
                "last4": "9012",
                "card_id": "card_user3"
            },
        },
        {
            "order_id": "user4_test_001",
            "product_name": "2500 Gems",
            "product_type": "gems",
            "game": "clash-royale",
            "amount": 19.99,
            "currency": "USD",
            "user_account": "user4@test.com",
            "payment_method": "google_pay",
            "card_info": {
                "last4": "3456",
                "card_id": "card_user4"
            },
        },
        {
            "order_id": "user5_test_001",
            "product_name": "Legendary Cards Pack",
            "product_type": "cards",
            "game": "clash-royale",
            "amount": 14.99,
            "currency": "USD",
            "user_account": "user5@test.com",
            "payment_method": "google_pay",
            "card_info": {
                "last4": "7890",
                "card_id": "card_user5"
            },
        },
    ]

    print("🚀 Создание тестовых заказов для первых 5 пользователей...\n")

    results = []
    for i, order in enumerate(test_orders, 1):
        print(f"Заказ {i}/5: {order['order_id']} - {order['product_name']}")
        result = create_test_order(order)
        results.append({"order": order, "result": result})
        
        if result.get("success"):
            print(f"  ✅ Успешно создан: job_id={result.get('job_id')}")
        else:
            print(f"  ❌ Ошибка: {result.get('error', result.get('detail', 'Unknown'))}")
        
        # Небольшая задержка между заказами
        if i < len(test_orders):
            time.sleep(1)

    print("\n📊 Итоги:")
    successful = sum(1 for r in results if r["result"].get("success"))
    failed = len(results) - successful
    
    print(f"  ✅ Успешно: {successful}")
    print(f"  ❌ Ошибок: {failed}")
    
    # Сохранить результаты
    with open("test_orders_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Результаты сохранены в test_orders_results.json")


if __name__ == "__main__":
    # Проверка доступности API
    try:
        health = requests.get(f"{API_URL}/health", timeout=5)
        if health.status_code == 200:
            print("✅ API сервер доступен\n")
            main()
        else:
            print("❌ API сервер недоступен")
    except Exception as e:
        print(f"❌ Ошибка подключения к API: {e}")
        print("Убедитесь, что сервер запущен: docker-compose up -d")

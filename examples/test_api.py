"""Пример использования API для отправки заказа."""

import requests
import json

# URL API
API_URL = "http://localhost:8000/api/v1"

# Данные заказа
order_data = {
    "order_id": "test_12345",
    "product_name": "500 Gems",
    "product_type": "gems",
    "game": "clash-royale",
    "amount": 4.99,
    "currency": "USD",
    "user_account": "test@example.com",
    "payment_method": "google_pay",
    "card_info": {
        "last4": "1234",
        "card_id": "card_test123",
    },
}

# Отправка заказа
response = requests.post(
    f"{API_URL}/orders/process",
    json=order_data,
    headers={"Content-Type": "application/json"},
)

print(f"Status Code: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2)}")

# Проверка health
health_response = requests.get(f"{API_URL}/health")
print(f"\nHealth Check: {health_response.json()}")

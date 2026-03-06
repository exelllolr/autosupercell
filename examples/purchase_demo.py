"""Демонстрация покупки товара в магазине Brawl Stars."""

import os
from pathlib import Path

import requests

API_URL = os.environ.get("AUTOSUPERCELL_API_URL", "http://localhost:8000/api/v1")
REQUEST_TIMEOUT = 600  # 10 минут

# Если в .env или окружении задан API_SECRET_KEY — передаём его во всех запросах.
# Пример: set AUTOSUPERCELL_API_KEY=ваш_ключ (Windows) или export ... (Linux/macOS)
API_KEY = os.environ.get("AUTOSUPERCELL_API_KEY", "")


# Заголовки, которые будут добавляться к каждому запросу
def _get_headers() -> dict:
    """Сформировать заголовки запроса (включая X-API-Key, если задан)."""
    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


def print_step(step_num: int, title: str, description: str):
    """Вывести информацию о шаге."""
    print(f"\n{'=' * 60}")
    print(f"ШАГ {step_num}: {title}")
    print(f"{'=' * 60}")
    print(description)
    print()


def demo_purchase(
    email: str,
    game: str = "brawl-stars",
    product_name: str = "80 Gems",
    verification_code: str = "",
    email_password: str = "",
):
    """Демонстрация покупки товара."""
    print_step(
        1,
        "Покупка товара в Supercell Store",
        f"""
Email: {email}
Игра: {game}
Товар: {product_name}

Процесс (авторизация как в supercell_full_auth_demo):
1. Открытие store.supercell.com, принятие cookies
2. Клик «Log in» → ждём редирект на accounts.supercell.com
   (если редиректа нет — переходим на accounts.supercell.com/login)
3. Ввод email (130 мс/символ) + клик LOG IN (движение мыши)
4. Ввод кода верификации из письма Supercell
5. На главной store — клик по карточке магазина игры (например «Brawl Stars Store»)
6. AI ищет товар "{product_name}" и нажимает «Buy»
7. Добавление в корзину → открытие окна оплаты (checkout)
        """.strip(),
    )

    data = {
        "email": email,
        "game": game,
        "product_name": product_name,
        "product_type": "gems",
    }
    if verification_code:
        data["verification_code"] = verification_code
    if email_password:
        data["email_password"] = email_password

    # Проверка прокси на сервере (API читает .env и proxies.txt)
    try:
        proxy_status = requests.get(
            f"{API_URL}/proxy/status", timeout=5, headers=_get_headers()
        )
        if proxy_status.status_code == 200:
            ps = proxy_status.json()
            if ps.get("proxy_enabled") and ps.get("proxies_loaded", 0) > 0:
                print(
                    f"   [Прокси] Загружено: {ps['proxies_loaded']}, будут использоваться при открытии браузера."
                )
            else:
                print(
                    f"   [Прокси] Не используются: {ps.get('message', 'PROXY_ENABLED или proxies.txt не настроены.')}"
                )
    except Exception:
        pass

    print("Отправка запроса...")
    print(f"   Endpoint: POST {API_URL}/supercell/purchase")
    print(
        f"   Таймаут: {REQUEST_TIMEOUT // 60} мин. Ожидайте ответа (браузер + авторизация), не прерывайте (Ctrl+C)."
    )
    print()

    try:
        response = requests.post(
            f"{API_URL}/supercell/purchase",
            json=data,
            timeout=REQUEST_TIMEOUT,
            headers=_get_headers(),
        )

        if response.status_code == 200:
            result = response.json()
            print("✅ Процесс завершён!")
            print(f"   Успех: {result.get('success')}")
            print(f"   Товар добавлен в корзину: {result.get('added_to_cart')}")
            print(
                f"   Окно оформления заказа открыто: {result.get('checkout_opened', False)}"
            )
            print(f"   Сообщение: {result.get('message')}")
            print(f"   URL: {result.get('url')}")

            # Результат оплаты Google Pay
            payment = result.get("payment")
            if payment:
                print(f"\n   💳 Google Pay:")
                print(f"      Кнопка нажата: {payment.get('google_pay_clicked')}")
                print(f"      Оплата подтверждена: {payment.get('payment_confirmed')}")
                print(f"      Успех верифицирован: {payment.get('payment_verified')}")
                if payment.get("error"):
                    print(f"      Ошибка: {payment.get('error')}")

            if result.get("video"):
                print(f"   Видео сессии: {result.get('video')}")
            if result.get("checkout_screenshot"):
                print(f"   Скриншот checkout: {result.get('checkout_screenshot')}")

            if result.get("product_info"):
                product_info = result["product_info"]
                print(f"\n   Информация о товаре:")
                print(f"      Название: {product_name}")
                print(f"      Цена: {product_info.get('price', 'N/A')}")
                conf = product_info.get("confidence")
                print(
                    f"      Уверенность AI: {conf:.2%}"
                    if conf is not None
                    else "      Уверенность AI: N/A"
                )
                print(f"      Описание: {product_info.get('description', 'N/A')}")

            if result.get("screenshot"):
                print(f"\n   Скриншот: {result.get('screenshot')}")
            if "proxy_used" in result:
                print(f"\n   Прокси использовался: {result.get('proxy_used')}")
                if result.get("proxy_server"):
                    print(f"   Прокси-сервер: {result['proxy_server']}")

            return result

        else:
            print(f"❌ Ошибка: {response.status_code}")
            try:
                error_detail = response.json() if response.content else {}
            except (ValueError, requests.exceptions.JSONDecodeError):
                error_detail = {
                    "detail": response.text[:500]
                    if response.text
                    else "Ответ не в формате JSON"
                }
            detail = error_detail.get(
                "detail", error_detail.get("error", "Unknown error")
            )
            print(f"   Детали: {detail}")
            if isinstance(detail, dict):
                if detail.get("screenshot"):
                    print(f"   Скриншот ошибки: {detail['screenshot']}")
                if detail.get("video"):
                    print(f"   Видео сессии: {detail['video']}")
                if detail.get("hint"):
                    print(f"\n   Подсказка: {detail['hint']}")
                if "proxy_used" in detail:
                    print(
                        f"   Прокси использовался: {detail.get('proxy_used')}; сервер: {detail.get('proxy_server', 'N/A')}"
                    )
            else:
                print(f"   Ответ сервера: {str(detail)[:400]}")
            return None

    except requests.exceptions.Timeout:
        print("❌ Таймаут запроса (процесс занял более 10 минут)")
        print("   Возможные причины:")
        print("   - Прокси работает медленно")
        print("   - Supercell долго отвечает")
        print("   - AI поиск занял много времени")
        print("   Если используете nginx — убедитесь, что proxy_read_timeout >= 720s")
        print("   (см. nginx/nginx.conf в корне проекта)")
        return None
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None


if __name__ == "__main__":
    print("=" * 60)
    print("ДЕМОНСТРАЦИЯ ПОКУПКИ ТОВАРА")
    print("=" * 60)

    # Проверка доступности API (Docker поднимает приложение ~15 сек — таймаут 20 сек)
    if API_KEY:
        print(
            f"🔑 API-ключ задан (X-API-Key: {'*' * (len(API_KEY) - 4)}{API_KEY[-4:]})"
        )
    else:
        print(
            "ℹ️  API-ключ не задан (AUTOSUPERCELL_API_KEY не установлен). "
            "Если на сервере включён API_SECRET_KEY — запросы будут отклонены."
        )

    try:
        health_response = requests.get(
            f"{API_URL}/health", timeout=20, headers=_get_headers()
        )
        if health_response.status_code == 200:
            print("✅ API сервер доступен")
        else:
            print("⚠️  API сервер отвечает, но статус не 200")
    except Exception:
        print("❌ API сервер недоступен!")
        print(
            "   Локально: python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
        )
        print(
            "   Docker:   docker-compose up -d  затем подождите 15–20 сек и проверьте: curl -s http://localhost:8000/api/v1/health"
        )
        print(
            "   Если только что запустили контейнеры — подождите и запустите скрипт снова."
        )
        exit(1)

    print("\n" + "=" * 60)
    print("Покупка товара в магазине Brawl Stars")
    print("=" * 60)

    email = input("Email Supercell аккаунта: ").strip()
    if not email:
        print("❌ Email не может быть пустым")
        exit(1)

    print()
    print("Код верификации:")
    print("  - Введите код сейчас (если уже получили письмо от Supercell)")
    print(
        "  - Нажмите Enter — тогда у вас будет 2 минуты ввести код вручную в браузере"
    )
    print(
        "  - Или введите пароль от email на следующем шаге — код придёт автоматически"
    )
    verification_code = input("Код верификации (или Enter): ").strip()

    email_password = ""
    if not verification_code:
        email_password = input(
            "Пароль от email для авто-получения кода (или Enter — ввод вручную): "
        ).strip()

    game = (
        input("\nИгра (brawl-stars / clash-royale, по умолчанию brawl-stars): ").strip()
        or "brawl-stars"
    )
    product_name = (
        input("Название товара (по умолчанию '80 Gems'): ").strip() or "80 Gems"
    )

    result = demo_purchase(
        email=email,
        game=game,
        product_name=product_name,
        verification_code=verification_code,
        email_password=email_password,
    )

    print("\n" + "=" * 60)
    if result:
        print("✅ Демонстрация завершена успешно!")
        print(f"   Скриншоты: screenshots/")
        if result.get("video"):
            print(f"   Видео: {result['video']}")
    else:
        print("❌ Демонстрация завершена с ошибкой")
        print("   Проверьте логи: logs/autosupercell.log")
        print("   Скриншоты ошибки: screenshots/")
    print("=" * 60)

"""Визуальная демонстрация полной авторизации: Supercell Store + Google."""

import requests
import json
import time
from pathlib import Path

API_URL = "http://localhost:8000/api/v1"
# Таймаут запроса: сценарий (спиннер, ожидание кода, прокси) может занимать до 10 мин
REQUEST_TIMEOUT = 600


def print_step(step_num: int, title: str, description: str):
    """Вывести информацию о шаге."""
    print(f"\n{'='*60}")
    print(f"ШАГ {step_num}: {title}")
    print(f"{'='*60}")
    print(description)
    print()


def demo_full_auth(supercell_email: str, supercell_email_password: str, google_email: str, google_password: str = None, supercell_code: str = None):
    """Демонстрация полной авторизации."""
    print_step(
        1,
        "Полная авторизация: Supercell Store + Google",
        f"""
Supercell: {supercell_email}
Google: {google_email}

Процесс:
1. Открытие store.supercell.com
2. Принятие cookies
3. Авторизация в Supercell Store (email + код из email)
4. Переход в настройки аккаунта
5. Привязка Google аккаунта
6. Авторизация в Google
7. Подтверждение привязки
        """.strip(),
    )

    data = {
        "supercell_email": supercell_email,
        "google_email": google_email,
    }
    
    if supercell_email_password:
        data["supercell_email_password"] = supercell_email_password
    
    if supercell_code:
        data["supercell_verification_code"] = supercell_code
    
    if google_password:
        data["google_password"] = google_password

    print("📤 Отправка запроса...")
    print(f"   Endpoint: POST {API_URL}/supercell/full-auth")
    
    try:
        response = requests.post(
            f"{API_URL}/supercell/full-auth",
            json=data,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 200:
            result = response.json()
            print("✅ Процесс завершён!")
            print(f"   Успех: {result.get('success')}")
            print(f"   Сообщение: {result.get('message')}")
            print(f"   Финальный URL: {result.get('final_url')}")
            print(f"\n   Скриншоты ({len(result.get('screenshots', []))} шт.):")
            for i, screenshot in enumerate(result.get("screenshots", []), 1):
                print(f"      {i}. {screenshot}")
            
            return result
        else:
            print(f"❌ Ошибка: {response.status_code}")
            error_detail = response.json() if response.content else {}
            print(f"   Детали: {error_detail.get('detail', 'Unknown error')}")
            if error_detail.get('detail', {}).get('screenshot'):
                print(f"   Скриншот ошибки: {error_detail['detail']['screenshot']}")
            return None

    except requests.exceptions.Timeout:
        print("❌ Таймаут запроса (процесс занял более 5 минут)")
        print("   Возможные причины:")
        print("   - Прокси работает медленно")
        print("   - Supercell долго отвечает")
        print("   - Проверьте логи сервера: docker logs autosupercell-app")
        return None
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None


def demo_supercell_login(email: str, email_password: str = None, verification_code: str = None):
    """Демонстрация авторизации только в Supercell Store."""
    print_step(
        1,
        "Авторизация в Supercell Store",
        f"Email: {email}\nПроцесс: Открытие store.supercell.com → Принятие cookies → Вход → Код из email → Проверка",
    )

    data = {
        "email": email,
    }
    
    if email_password:
        data["email_password"] = email_password
    
    if verification_code:
        data["verification_code"] = verification_code

    print("📤 Отправка запроса...")
    print("   (при прокси первая загрузка может занять до ~60 сек)")
    print(f"   (таймаут запроса: {REQUEST_TIMEOUT // 60} мин)")
    response = requests.post(
        f"{API_URL}/supercell/login", json=data, timeout=REQUEST_TIMEOUT
    )

    if response.status_code == 200:
        result = response.json()
        if result.get("authenticated"):
            print("✅ Авторизация успешна!")
        else:
            print("⚠️ Вход не завершён — до окна ввода кода не дошли. Проверьте скриншот и видео.")
        print(f"   Session ID: {result.get('session_id')}")
        print(f"   URL: {result.get('url')}")
        print(f"   Статус: {result.get('message')}")
        print(f"   Скриншот: {result.get('screenshot')}")
        if result.get("video"):
            print(f"   Видео сессии: {result.get('video')}")
        return result
    else:
        print(f"❌ Ошибка: {response.status_code}")
        error_detail = response.json() if response.content else {}
        error_msg = error_detail.get('detail', {}).get('error', 'Unknown error')
        print(f"   Детали: {error_msg}")
        
        # Показываем подсказку для ошибок Gmail
        if "App Password" in error_msg or "Application-specific password" in error_msg:
            print("\n" + "="*60)
            print("💡 РЕШЕНИЕ:")
            print("="*60)
            print("1. Создайте App Password: https://myaccount.google.com/apppasswords")
            print("2. Используйте 16-значный App Password вместо обычного пароля")
            print("3. Подробная инструкция: GMAIL_APP_PASSWORD_GUIDE.md")
            print("="*60)
        
        if error_detail.get('detail', {}).get('screenshot'):
            print(f"   Скриншот ошибки: {error_detail['detail']['screenshot']}")
        return None


def main():
    """Главная функция демонстрации."""
    print("\n" + "="*60)
    print("🎬 ВИЗУАЛЬНАЯ ДЕМОНСТРАЦИЯ")
    print("   Полная авторизация: Supercell Store + Google")
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

    # Выбор режима
    print("Выберите режим:")
    print("1. Полная авторизация (Supercell + Google)")
    print("2. Только Supercell Store")
    
    choice = input("\nВаш выбор (1 или 2): ").strip()

    if choice == "1":
        # Полная авторизация
        print("\n" + "="*60)
        print("📧 Полная авторизация: Supercell Store + Google")
        print("="*60)
        print("Введите email и код верификации из письма Supercell")
        print("="*60 + "\n")
        
        supercell_email = input("Введите email Supercell аккаунта: ").strip()
        supercell_code = input("Введите код верификации Supercell из email: ").strip() or None
        
        if not supercell_code:
            print("\n⚠️  Код верификации обязателен!")
            print("Проверьте письмо от Supercell и введите 6-значный код.")
            return
        
        # Убираем пробелы из кода (на случай если пользователь ввел "400 991" вместо "400991")
        supercell_code = supercell_code.replace(" ", "").replace("-", "")
        
        if len(supercell_code) != 6 or not supercell_code.isdigit():
            print(f"\n⚠️  Неверный формат кода! Код должен быть 6 цифр, получено: '{supercell_code}'")
            return
            
        google_email = input("Введите email Google аккаунта: ").strip()
        google_password = input("Введите пароль Google (Enter для пропуска): ").strip() or None

        result = demo_full_auth(
            supercell_email, None, google_email, google_password, supercell_code
        )

        if result:
            # Сохранить результаты
            results_file = Path("supercell_full_auth_results.json")
            with open(results_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"\n💾 Результаты сохранены в {results_file}")

    else:
        # Только Supercell
        print("\n" + "="*60)
        print("📧 Авторизация в Supercell Store")
        print("="*60)
        print("Введите email и код верификации из письма Supercell")
        print("="*60 + "\n")
        
        email = input("Введите email Supercell аккаунта: ").strip()
        verification_code = input("Введите код верификации из email: ").strip() or None
        
        if not verification_code:
            print("\n⚠️  Код верификации обязателен!")
            print("Проверьте письмо от Supercell и введите 6-значный код.")
            return
        
        # Убираем пробелы из кода (на случай если пользователь ввел "400 991" вместо "400991")
        verification_code = verification_code.replace(" ", "").replace("-", "")
        
        if len(verification_code) != 6 or not verification_code.isdigit():
            print(f"\n⚠️  Неверный формат кода! Код должен быть 6 цифр, получено: '{verification_code}'")
            return

        result = demo_supercell_login(email, None, verification_code)

    print("\n📸 Скриншоты доступны в директории screenshots/")
    print("   Используйте команду: docker exec autosupercell-app ls -la screenshots/")


if __name__ == "__main__":
    main()

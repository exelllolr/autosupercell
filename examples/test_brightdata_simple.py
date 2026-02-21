"""Простой тест Bright Data прокси без зависимостей."""

import requests
import urllib3
import sys
import os

# Настройка кодировки для Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# API ключ из proxies.txt
API_KEY = "dcf4e874-9d06-4109-9abf-1c1460ab8081"

def test_brightdata():
    """Тест Bright Data прокси."""
    print("=" * 60)
    print("🧪 ТЕСТИРОВАНИЕ BRIGHT DATA ПРОКСИ")
    print("=" * 60)
    
    # Формируем прокси URL (пробуем разные форматы)
    # Bright Data может требовать пароль или использовать другой формат
    print("\nПробуем разные форматы прокси...")
    
    proxy_formats = [
        f"http://{API_KEY}-country-us:@brd.superproxy.io:33335",  # Без пароля
        f"http://{API_KEY}-country-us:{API_KEY}@brd.superproxy.io:33335",  # С паролем = API ключ
        f"http://{API_KEY}-country-us:@brd.superproxy.io:33335",  # Пустой пароль (исправлено)
    ]
    
    working_proxy = None
    for proxy_url in proxy_formats:
        print(f"\nПробуем: {proxy_url[:50]}...")
        proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        
        try:
            response = requests.get(
                "https://geo.brdtest.com/welcome.txt?product=resi&method=native",
                proxies=proxies,
                timeout=10,
                verify=False
            )
            if response.status_code == 200:
                print(f"✅ Работает! Формат: {proxy_url[:50]}...")
                working_proxy = proxy_url
                break
        except Exception as e:
            print(f"❌ Не работает: {str(e)[:100]}")
            continue
    
    if not working_proxy:
        print("\n❌ Ни один формат не сработал.")
        print("\n💡 Проверьте:")
        print("   1. Правильность API ключа")
        print("   2. Активность подписки Bright Data")
        print("   3. Баланс на аккаунте")
        print("   4. Доступность порта 33335")
        return False
    
    proxies = {
        "http": working_proxy,
        "https": working_proxy,
    }
    
    print(f"\n📡 Используем Proxy URL: {working_proxy[:60]}...")
    
    # Тест 1: Проверка геолокации
    print("\n📋 Тест 1: Проверка геолокации через Bright Data...")
    try:
        response = requests.get(
            "https://geo.brdtest.com/welcome.txt?product=resi&method=native",
            proxies=proxies,
            timeout=30,
            verify=False
        )
        
        if response.status_code == 200:
            print("✅ Успешно подключено!")
            print("\n📊 Информация о прокси:")
            print(response.text)
            
            # Парсим информацию
            lines = response.text.strip().split('\n')
            info = {}
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    info[key.strip()] = value.strip()
            
            print(f"\n🌍 Страна: {info.get('Country', 'N/A')}")
            print(f"🏙️  Город: {info.get('City', 'N/A')}")
            print(f"📍 Регион: {info.get('Region', 'N/A')}")
            print(f"🔢 IP версия: {info.get('IP version', 'N/A')}")
            print(f"🏢 ASN: {info.get('ASN number', 'N/A')}")
        else:
            print(f"❌ Ошибка: HTTP {response.status_code}")
            print(f"   Ответ: {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return False
    
    # Тест 2: Проверка доступа к Supercell Store
    print("\n📋 Тест 2: Проверка доступа к Supercell Store...")
    try:
        response = requests.get(
            "https://store.supercell.com",
            proxies=proxies,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            verify=False
        )
        
        if response.status_code == 200:
            print("✅ Supercell Store доступен через прокси!")
            print(f"   Размер ответа: {len(response.content)} байт")
            print(f"   Заголовок: {response.headers.get('Content-Type', 'N/A')}")
        else:
            print(f"⚠️  HTTP {response.status_code} (может быть нормально)")
            
    except Exception as e:
        print(f"❌ Ошибка доступа к Supercell Store: {e}")
        return False
    
    # Тест 3: Проверка IP адреса
    print("\n📋 Тест 3: Проверка внешнего IP адреса...")
    try:
        response = requests.get(
            "https://api.ipify.org?format=json",
            proxies=proxies,
            timeout=30,
            verify=False
        )
        
        if response.status_code == 200:
            ip_info = response.json()
            print(f"✅ Внешний IP: {ip_info.get('ip')}")
        else:
            print(f"⚠️  Не удалось получить IP (HTTP {response.status_code})")
            
    except Exception as e:
        print(f"⚠️  Ошибка получения IP: {e}")
    
    print("\n" + "=" * 60)
    print("✅ Тестирование завершено!")
    print("=" * 60)
    print("\n💡 Если все тесты прошли успешно, прокси готов к использованию!")
    print("   Запустите авторизацию: python examples/supercell_full_auth_demo.py")
    
    return True

if __name__ == "__main__":
    test_brightdata()

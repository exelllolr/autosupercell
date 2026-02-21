"""Тестирование Bright Data прокси."""

import requests
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.proxy_manager import proxy_manager


def test_brightdata_proxy():
    """Тест подключения через Bright Data прокси."""
    print("=" * 60)
    print("🧪 ТЕСТИРОВАНИЕ BRIGHT DATA ПРОКСИ")
    print("=" * 60)
    
    # Получаем прокси
    proxy = proxy_manager.get_proxy()
    
    if not proxy:
        print("❌ Прокси не найдены")
        print("Проверьте файл proxies.txt и настройки PROXY_ENABLED")
        return False
    
    print(f"\n📡 Используемый прокси:")
    print(f"   Server: {proxy.get('server')}")
    print(f"   Username: {proxy.get('username', 'N/A')}")
    print(f"   Password: {'***' if proxy.get('password') else 'N/A'}")
    
    # Формируем прокси URL для requests
    if proxy.get('username'):
        proxy_url = f"http://{proxy['username']}:{proxy.get('password', '')}@{proxy['server'].replace('http://', '')}"
    else:
        proxy_url = proxy['server']
    
    proxies = {
        "http": proxy_url,
        "https": proxy_url,
    }
    
    print(f"\n🔗 Proxy URL: {proxy_url}")
    
    # Тест 1: Проверка геолокации через Bright Data
    print("\n📋 Тест 1: Проверка геолокации через Bright Data...")
    try:
        response = requests.get(
            "https://geo.brdtest.com/welcome.txt?product=resi&method=native",
            proxies=proxies,
            timeout=30,
            verify=False  # Отключаем проверку SSL для теста
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
            
            if 'Country' in info:
                print(f"\n🌍 Страна: {info.get('Country')}")
            if 'City' in info:
                print(f"🏙️  Город: {info.get('City')}")
            if 'IP version' in info:
                print(f"🔢 IP версия: {info.get('IP version')}")
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
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        
        if response.status_code == 200:
            print("✅ Supercell Store доступен через прокси!")
            print(f"   Размер ответа: {len(response.content)} байт")
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
            timeout=30
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
    
    return True


if __name__ == "__main__":
    # Отключаем предупреждения SSL
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    success = test_brightdata_proxy()
    sys.exit(0 if success else 1)

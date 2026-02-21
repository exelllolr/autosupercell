"""Тест улучшенного stealth режима с Webshare прокси."""

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

def test_stealth_detection():
    """Тест детекции автоматизации через различные сервисы."""
    print("=" * 60)
    print("🛡️  ТЕСТИРОВАНИЕ STEALTH РЕЖИМА")
    print("=" * 60)
    
    # Читаем прокси из файла
    proxies = []
    try:
        with open("proxies.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                # Формат host:port:user:pass
                if line.count(":") == 3:
                    parts = line.split(":")
                    host, port, user, password = parts
                    proxy_url = f"http://{user}:{password}@{host}:{port}/"
                    proxies.append(proxy_url)
    except Exception as e:
        print(f"❌ Ошибка чтения proxies.txt: {e}")
        return False
    
    if not proxies:
        print("❌ Прокси не найдены в proxies.txt")
        return False
    
    print(f"\n📡 Найдено {len(proxies)} прокси")
    
    # Тестируем каждый прокси
    for i, proxy_url in enumerate(proxies, 1):
        print(f"\n{'='*60}")
        print(f"Прокси {i}/{len(proxies)}")
        print(f"{'='*60}")
        
        proxy_dict = {
            "http": proxy_url,
            "https": proxy_url,
        }
        
        # Тест 1: Проверка IP
        print("\n📋 Тест 1: Проверка IP адреса...")
        try:
            response = requests.get(
                "https://api.ipify.org?format=json",
                proxies=proxy_dict,
                timeout=15,
                verify=False
            )
            if response.status_code == 200:
                ip_info = response.json()
                print(f"✅ IP: {ip_info.get('ip')}")
            else:
                print(f"⚠️  HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            continue
        
        # Тест 2: Проверка доступа к Supercell Store
        print("\n📋 Тест 2: Доступ к Supercell Store...")
        try:
            response = requests.get(
                "https://store.supercell.com",
                proxies=proxy_dict,
                timeout=20,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
                verify=False
            )
            if response.status_code == 200:
                print(f"✅ Supercell Store доступен (размер: {len(response.content)} байт)")
            else:
                print(f"⚠️  HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
        
        # Тест 3: Проверка детекции автоматизации
        print("\n📋 Тест 3: Проверка детекции автоматизации...")
        try:
            # Используем сервис для проверки webdriver флага
            response = requests.get(
                "https://bot.sannysoft.com/",
                proxies=proxy_dict,
                timeout=20,
                verify=False
            )
            if response.status_code == 200:
                content = response.text.lower()
                if "webdriver" in content and "false" in content:
                    print("✅ Webdriver флаг не обнаружен")
                else:
                    print("⚠️  Возможна детекция webdriver")
        except Exception as e:
            print(f"⚠️  Не удалось проверить: {e}")
    
    print("\n" + "=" * 60)
    print("✅ Тестирование завершено!")
    print("=" * 60)
    print("\n💡 Для полного теста stealth используйте браузер через API:")
    print("   python examples/supercell_full_auth_demo.py")
    
    return True

if __name__ == "__main__":
    test_stealth_detection()

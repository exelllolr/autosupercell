"""Тест всех прокси из proxies.txt."""

import requests
import urllib3
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

# Настройка кодировки для Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def load_proxies(proxy_file: str = "proxies.txt") -> List[Dict[str, str]]:
    """
    Загрузка прокси из файла.
    
    Поддерживаемые форматы:
    - host:port
    - host:port:user:pass
    - user:pass@host:port
    """
    proxies = []
    proxy_path = Path(proxy_file)
    
    if not proxy_path.exists():
        print(f"❌ Файл {proxy_file} не найден!")
        return proxies
    
    try:
        with open(proxy_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                try:
                    # Формат 0: host:port (без авторизации)
                    if line.count(":") == 1 and "@" not in line:
                        host, port = line.split(":")
                        proxy_dict = {
                            "host": host,
                            "port": port,
                            "username": "",
                            "password": "",
                            "proxy_url": f"http://{host}:{port}",
                        }
                    # Формат 1: host:port:user:pass
                    elif line.count(":") == 3:
                        parts = line.split(":")
                        host, port, user, password = parts
                        proxy_dict = {
                            "host": host,
                            "port": port,
                            "username": user,
                            "password": password,
                            "proxy_url": f"http://{user}:{password}@{host}:{port}/",
                        }
                    # Формат 2: user:pass@host:port
                    elif "@" in line:
                        auth, proxy = line.split("@")
                        user, password = auth.split(":")
                        host, port = proxy.split(":")
                        proxy_dict = {
                            "host": host,
                            "port": port,
                            "username": user,
                            "password": password,
                            "proxy_url": f"http://{user}:{password}@{host}:{port}/",
                        }
                    else:
                        print(f"⚠️  Строка {line_num}: неверный формат '{line}' (пропущена)")
                        continue
                    
                    proxies.append(proxy_dict)
                except ValueError as e:
                    print(f"⚠️  Строка {line_num}: ошибка парсинга '{line}': {e}")
                    continue
        
        print(f"✅ Загружено {len(proxies)} прокси из {proxy_file}")
        return proxies
    
    except Exception as e:
        print(f"❌ Ошибка чтения файла {proxy_file}: {e}")
        return proxies


def test_proxy_ip(proxies_dict: Dict) -> Optional[str]:
    """Тест 1: Проверка IP через Webshare API."""
    try:
        response = requests.get(
            "https://ipv4.webshare.io/",
            proxies={
                "http": proxies_dict["proxy_url"],
                "https": proxies_dict["proxy_url"],
            },
            timeout=15,
            verify=False
        )
        
        if response.status_code == 200:
            return response.text.strip()
        return None
    except Exception:
        return None


def test_supercell_store(proxies_dict: Dict) -> bool:
    """Тест 2: Проверка доступа к Supercell Store."""
    try:
        response = requests.get(
            "https://store.supercell.com",
            proxies={
                "http": proxies_dict["proxy_url"],
                "https": proxies_dict["proxy_url"],
            },
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            verify=False
        )
        
        return response.status_code == 200
    except Exception:
        return False


def test_ip_geolocation(proxies_dict: Dict) -> Optional[Dict]:
    """Тест 3: Проверка геолокации IP."""
    try:
        response = requests.get(
            "https://ipapi.co/json/",
            proxies={
                "http": proxies_dict["proxy_url"],
                "https": proxies_dict["proxy_url"],
            },
            timeout=15,
            verify=False
        )
        
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None


def test_single_proxy(proxy_dict: Dict, proxy_num: int, total: int) -> Dict:
    """
    Тестирование одного прокси.
    
    Returns:
        Dict с результатами тестирования
    """
    host = proxy_dict["host"]
    port = proxy_dict["port"]
    username = proxy_dict.get("username") or "noauth"
    
    print(f"\n{'='*70}")
    print(f"🔍 Прокси {proxy_num}/{total}: {host}:{port} (user: {username})")
    print(f"{'='*70}")
    
    results = {
        "proxy": f"{host}:{port}",
        "username": username,
        "ip": None,
        "ip_test": False,
        "supercell_test": False,
        "geolocation": None,
        "status": "failed",
    }
    
    # Тест 1: IP
    print("📋 Тест 1: Проверка IP...", end=" ")
    ip = test_proxy_ip(proxy_dict)
    if ip:
        results["ip"] = ip
        results["ip_test"] = True
        print(f"✅ IP: {ip}")
    else:
        print("❌ Не удалось получить IP")
        return results
    
    # Тест 2: Supercell Store
    print("📋 Тест 2: Доступ к Supercell Store...", end=" ")
    if test_supercell_store(proxy_dict):
        results["supercell_test"] = True
        print("✅ Доступен")
    else:
        print("❌ Недоступен")
    
    # Тест 3: Геолокация
    print("📋 Тест 3: Геолокация...", end=" ")
    geo = test_ip_geolocation(proxy_dict)
    if geo:
        results["geolocation"] = geo
        country = geo.get("country_name", "N/A")
        city = geo.get("city", "N/A")
        org = geo.get("org", "N/A")
        print(f"✅ {country}, {city} ({org[:50] if org else 'N/A'})")
    else:
        print("⚠️  Не удалось получить геолокацию")
    
    # Определяем статус
    if results["ip_test"] and results["supercell_test"]:
        results["status"] = "success"
    elif results["ip_test"]:
        results["status"] = "partial"
    else:
        results["status"] = "failed"
    
    return results


def print_summary(all_results: List[Dict]):
    """Вывод сводки результатов тестирования."""
    print("\n" + "="*70)
    print("📊 СВОДКА РЕЗУЛЬТАТОВ")
    print("="*70)
    
    total = len(all_results)
    success = sum(1 for r in all_results if r["status"] == "success")
    partial = sum(1 for r in all_results if r["status"] == "partial")
    failed = sum(1 for r in all_results if r["status"] == "failed")
    
    print(f"\nВсего прокси: {total}")
    print(f"✅ Успешных (IP + Supercell): {success}")
    print(f"⚠️  Частично рабочих (только IP): {partial}")
    print(f"❌ Не работающих: {failed}")
    
    if success > 0:
        print("\n✅ РАБОТАЮЩИЕ ПРОКСИ:")
        for i, result in enumerate(all_results, 1):
            if result["status"] == "success":
                geo = result.get("geolocation", {})
                country = geo.get("country_name", "N/A") if geo else "N/A"
                print(f"   {i}. {result['proxy']} ({result['ip']}) - {country}")
    
    if partial > 0:
        print("\n⚠️  ЧАСТИЧНО РАБОТАЮЩИЕ (только IP, без Supercell):")
        for i, result in enumerate(all_results, 1):
            if result["status"] == "partial":
                geo = result.get("geolocation", {})
                country = geo.get("country_name", "N/A") if geo else "N/A"
                print(f"   {i}. {result['proxy']} ({result['ip']}) - {country}")
    
    if failed > 0:
        print("\n❌ НЕ РАБОТАЮЩИЕ ПРОКСИ:")
        for i, result in enumerate(all_results, 1):
            if result["status"] == "failed":
                print(f"   {i}. {result['proxy']}")
    
    print("\n" + "="*70)


def main():
    """Главная функция тестирования."""
    print("="*70)
    print("🧪 ТЕСТИРОВАНИЕ ВСЕХ ПРОКСИ ИЗ proxies.txt")
    print("="*70)
    print(f"⏰ Время начала: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Загружаем прокси
    proxies = load_proxies("proxies.txt")
    
    if not proxies:
        print("\n❌ Нет прокси для тестирования!")
        return
    
    # Тестируем каждый прокси
    all_results = []
    for i, proxy_dict in enumerate(proxies, 1):
        result = test_single_proxy(proxy_dict, i, len(proxies))
        all_results.append(result)
    
    # Выводим сводку
    print_summary(all_results)
    
    print(f"\n⏰ Время завершения: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n💡 Рекомендации:")
    if any(r["status"] == "success" for r in all_results):
        print("   ✅ Есть рабочие прокси — можно использовать для авторизации")
    else:
        print("   ⚠️  Нет полностью рабочих прокси — проверьте настройки или обновите список")
    print("   📝 Запуск авторизации: python examples/supercell_full_auth_demo.py")


if __name__ == "__main__":
    main()

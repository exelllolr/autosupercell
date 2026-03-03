"""
Тест входа в Supercell Store с расширением US Region и прокси/VPN на US.

Перед запуском:
1. В .env установите:
   BROWSER_USE_US_EXTENSION=true
   BROWSER_HEADLESS=false
   BROWSER_USE_PERSISTENT_PROFILE=true
   PROXY_ENABLED=true   # и настройте прокси на US (proxies.txt или Novada region=us)
   BROWSER_USE_PATCHRIGHT=false   # расширения работают с Chromium; при true channel сбрасывается на Chromium

2. Либо запустите с переменными окружения (Windows PowerShell):
   $env:BROWSER_USE_US_EXTENSION="true"; $env:BROWSER_HEADLESS="false"
   .\\venv\\Scripts\\python.exe examples/test_login_with_us_extension.py

3. Расширение: browser_extensions/us_region/ — подменяет geolocation на US (New York).
   Запуск только с видимым окном (headless=false) и persistent context.
"""
import asyncio
import os
import sys

# Принудительно включаем расширение и видимый браузер для этого скрипта
os.environ.setdefault("BROWSER_USE_US_EXTENSION", "true")
os.environ.setdefault("BROWSER_HEADLESS", "false")
os.environ.setdefault("BROWSER_USE_PERSISTENT_PROFILE", "true")

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from app.config import settings
    from app.core.browser_automation import BrowserAutomation

    print("=" * 60)
    print("ТЕСТ ВХОДА С РАСШИРЕНИЕМ US REGION")
    print("=" * 60)
    print(f"  BROWSER_USE_US_EXTENSION: {getattr(settings, 'BROWSER_USE_US_EXTENSION', False)}")
    print(f"  BROWSER_HEADLESS:         {getattr(settings, 'BROWSER_HEADLESS', True)}")
    print(f"  PROXY_ENABLED:           {getattr(settings, 'PROXY_ENABLED', False)}")
    print("=" * 60)
    print("Запуск браузера с расширением (откроется окно Chromium)...")
    print()

    browser = BrowserAutomation()
    try:
        await browser.start()
        print("Браузер запущен. Переход на store.supercell.com ...")
        await browser.page.goto(
            "https://store.supercell.com",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await browser.page.wait_for_timeout(3000)
        print("Страница загружена. Проверьте в браузере:")
        print("  - Откройте DevTools (F12) → Console, выполните:")
        print('    navigator.geolocation.getCurrentPosition(p => console.log("Geo:", p.coords))')
        print("  - Должны увидеть latitude: 40.7128, longitude: -74.0060 (New York)")
        print()
        print("Ожидание 30 сек — можно вручную нажать Log in и проверить вход.")
        await browser.page.wait_for_timeout(30000)
    finally:
        await browser.close()
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())

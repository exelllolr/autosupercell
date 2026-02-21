"""
Быстрая проверка stealth — консольный вывод всех значений + скриншот.
Запуск: python examples/check_stealth_now.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Патч с Proxy — единственный способ скрыть 'webdriver' от оператора 'in'
PATCH = """
(function() {
    // 1. Удаляем с прототипа и напрямую
    try { delete Object.getPrototypeOf(navigator).webdriver; } catch(e) {}
    try { delete navigator.webdriver; } catch(e) {}

    // 2. Переопределяем через defineProperty
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined, set: () => {}, configurable: true, enumerable: false
        });
    } catch(e) {}

    // 3. Proxy на navigator — скрывает 'webdriver' от оператора 'in'
    // Это единственный способ сделать ('webdriver' in navigator) === false
    try {
        const navProxy = new Proxy(navigator, {
            has: function(target, key) {
                if (key === 'webdriver') return false;
                return key in target;
            },
            get: function(target, key) {
                if (key === 'webdriver') return undefined;
                const val = target[key];
                if (typeof val === 'function') return val.bind(target);
                return val;
            }
        });
        Object.defineProperty(window, 'navigator', {
            get: () => navProxy, configurable: true, enumerable: true
        });
    } catch(e) {}

    // 4. Cdc / Selenium ключи
    ['$cdc_asdjflasutopfhvcZLmcfl_','$chrome_asyncScriptInfo',
     '__webdriver_evaluate','__selenium_evaluate','__webdriver_script_function',
     '__driver_evaluate','_Selenium_IDE_Recorder'].forEach(function(k) {
        try { delete window[k]; } catch(e) {}
        try { Object.defineProperty(window, k, {get:()=>undefined, configurable:true, enumerable:false}); } catch(e) {}
    });

    // 5. Другие свойства
    try { Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true }); } catch(e) {}
    try { Object.defineProperty(navigator, 'deviceMemory', { get: () => 8, configurable: true }); } catch(e) {}
    try { Object.defineProperty(navigator, 'platform', { get: () => 'Win32', configurable: true }); } catch(e) {}
    try { Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'], configurable: true }); } catch(e) {}

    if (!window.chrome) {
        Object.defineProperty(window, 'chrome', { writable: true, enumerable: true, configurable: false, value: {} });
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = { id: undefined, connect: null, sendMessage: null };
    }
})();
"""


async def main():
    print("=" * 55)
    print("STEALTH CHECK — консольный вывод всех значений")
    print("=" * 55)

    Path("screenshots").mkdir(exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                "--disable-infobars",
                "--window-size=1280,900",
            ]
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=UA,
            locale="en-US",
            timezone_id="America/New_York",
        )

        # 1. page (без context init script — он в изолированном world)
        page = await ctx.new_page()

        # 2. CDP patch ТОЛЬКО — работает в основном контексте страницы
        # add_init_script работает в изолированном Playwright world — страница его НЕ видит!
        try:
            cdp = await ctx.new_cdp_session(page)
            # addScriptToEvaluateOnNewDocument — выполняется в основном world при каждой загрузке
            await cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": PATCH})
            # Runtime.evaluate — немедленно на текущей странице (about:blank)
            await cdp.send("Runtime.evaluate", {"expression": PATCH, "returnByValue": False})
            print("[OK] CDP patch applied")
        except Exception as e:
            print(f"[WARN] CDP: {e}")

        # 3. playwright-stealth (тоже через add_init_script — изолированный world,
        #    но некоторые её патчи работают через CDP внутри)
        await stealth_async(page)

        # 5. Проверяем значения ДО перехода на сайт
        print("\n--- Значения navigator ДО goto ---")
        vals = await page.evaluate("""() => ({
            webdriver:           navigator.webdriver,
            webdriverInNav:      'webdriver' in navigator,
            plugins:             navigator.plugins.length,
            languages:           Array.from(navigator.languages),
            platform:            navigator.platform,
            hardwareConcurrency: navigator.hardwareConcurrency,
            deviceMemory:        navigator.deviceMemory,
            chrome:              !!window.chrome,
            chromeRuntime:       !!(window.chrome && window.chrome.runtime),
            cdc:                 !!window.$cdc_asdjflasutopfhvcZLmcfl_,
            selenium:            !!window.__selenium_evaluate,
            userAgent:           navigator.userAgent.slice(0, 90),
            vendor:              navigator.vendor,
        })""")
        for k, v in vals.items():
            print(f"  {k:30s} = {v}")

        # 6. Переходим на bot.sannysoft.com
        print("\n--- Переходим на bot.sannysoft.com ---")
        await page.goto("https://bot.sannysoft.com", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # 7. Проверяем значения ПОСЛЕ перехода
        print("\n--- Значения navigator ПОСЛЕ goto ---")
        vals2 = await page.evaluate("""() => ({
            webdriver:           navigator.webdriver,
            webdriverInNav:      'webdriver' in navigator,
            plugins:             navigator.plugins.length,
            chrome:              !!window.chrome,
            chromeRuntime:       !!(window.chrome && window.chrome.runtime),
            cdc:                 !!window.$cdc_asdjflasutopfhvcZLmcfl_,
        })""")
        all_pass = True
        for k, v in vals2.items():
            ok = {
                "webdriver":     v is None or v is False,
                "webdriverInNav": not v,
                "plugins":       v > 0 if isinstance(v, int) else True,
                "chrome":        bool(v),
                "chromeRuntime": bool(v),
                "cdc":           not v,
            }.get(k, True)
            status = "[PASS]" if ok else "[FAIL]"
            if not ok:
                all_pass = False
            print(f"  {status} {k:30s} = {v}")

        print()
        if all_pass:
            print("  *** ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ ***")
        else:
            print("  *** ЕСТЬ ПРОБЛЕМЫ — смотри [FAIL] ***")

        # 8. Скриншоты
        await page.screenshot(
            path="screenshots/stealth_top.png",
            clip={"x": 0, "y": 0, "width": 800, "height": 350}
        )
        await page.screenshot(path="screenshots/stealth_full.png", full_page=True)
        print("\nСкриншоты: screenshots/stealth_top.png, stealth_full.png")

        await page.wait_for_timeout(3000)
        await browser.close()

    print("Готово!")


if __name__ == "__main__":
    asyncio.run(main())

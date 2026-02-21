"""
Прямой тест stealth — запускает браузер напрямую (без API сервера).
Открывает bot.sannysoft.com, делает скриншот и показывает что детектируется.

Запуск:
  python examples/test_stealth_direct.py
"""

import asyncio
import random
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# Максимально полный stealth скрипт — применяется через addScriptToEvaluateOnNewDocument
FULL_STEALTH_SCRIPT = """
(function() {
    'use strict';

    // 1. webdriver — удаляем и скрываем
    try { delete Object.getPrototypeOf(navigator).webdriver; } catch(e) {}
    try { delete navigator.webdriver; } catch(e) {}
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined, set: () => {},
            configurable: true, enumerable: false
        });
    } catch(e) {}

    // 1b. Proxy — делает ('webdriver' in navigator) === false
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

    // 2. Cdc / Selenium артефакты
    const cdcKeys = [
        '$cdc_asdjflasutopfhvcZLmcfl_',
        '$chrome_asyncScriptInfo',
        '__webdriver_evaluate',
        '__selenium_evaluate',
        '__webdriver_script_function',
        '__webdriver_script_func',
        '__webdriver_script_fn',
        '__fxdriver_evaluate',
        '__driver_unwrapped',
        '__webdriver_unwrapped',
        '__driver_evaluate',
        '__selenium_unwrapped',
        '__fxdriver_unwrapped',
        '_Selenium_IDE_Recorder',
        '_selenium',
        'calledSelenium',
    ];
    cdcKeys.forEach(function(k) {
        try { delete window[k]; } catch(e) {}
        try {
            Object.defineProperty(window, k, { get: () => undefined, configurable: true, enumerable: false });
        } catch(e) {}
    });

    // 3. Plugins — реалистичный список
    const mockPlugins = [
        {
            name: 'Chrome PDF Plugin',
            filename: 'internal-pdf-viewer',
            description: 'Portable Document Format',
            length: 1,
            item: function(i) { return this[i]; },
            namedItem: function(n) { return null; },
            refresh: function() {},
            0: { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' }
        },
        {
            name: 'Chrome PDF Viewer',
            filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
            description: '',
            length: 1,
            item: function(i) { return this[i]; },
            namedItem: function(n) { return null; },
            refresh: function() {},
            0: { type: 'application/pdf', suffixes: 'pdf', description: '' }
        },
        {
            name: 'Native Client',
            filename: 'internal-nacl-plugin',
            description: '',
            length: 2,
            item: function(i) { return this[i]; },
            namedItem: function(n) { return null; },
            refresh: function() {},
            0: { type: 'application/x-nacl', suffixes: '', description: 'Native Client Executable' },
            1: { type: 'application/x-pnacl', suffixes: '', description: 'Portable Native Client Executable' }
        }
    ];

    try {
        Object.defineProperty(navigator, 'plugins', {
            get: function() {
                const arr = Object.create(PluginArray.prototype);
                mockPlugins.forEach(function(p, i) {
                    const plugin = Object.create(Plugin.prototype);
                    Object.assign(plugin, p);
                    arr[i] = plugin;
                });
                arr.length = mockPlugins.length;
                arr.item = function(i) { return arr[i]; };
                arr.namedItem = function(n) {
                    for (let i = 0; i < arr.length; i++) {
                        if (arr[i].name === n) return arr[i];
                    }
                    return null;
                };
                arr.refresh = function() {};
                return arr;
            },
            configurable: true,
            enumerable: true
        });
    } catch(e) {}

    // 4. Languages
    try {
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
            configurable: true
        });
    } catch(e) {}

    // 5. window.chrome — полная имитация
    if (!window.chrome || !window.chrome.runtime) {
        window.chrome = {
            app: {
                isInstalled: false,
                InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
                getDetails: function() { return null; },
                getIsInstalled: function() { return false; },
                installState: function(cb) { cb('not_installed'); },
                runningState: function() { return 'cannot_run'; }
            },
            runtime: {
                OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
                OnRestartRequiredReason: { APP_UPDATE: 'app_update', GC_PRESSURE: 'gc_pressure', OS_UPDATE: 'os_update' },
                PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
                RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' },
                connect: function() { return { disconnect: function() {}, onDisconnect: { addListener: function() {} }, onMessage: { addListener: function() {} }, postMessage: function() {} }; },
                sendMessage: function() {},
                id: undefined
            },
            loadTimes: function() {
                return {
                    commitLoadTime: Date.now() / 1000 - Math.random() * 2,
                    connectionInfo: 'http/1.1',
                    finishDocumentLoadTime: Date.now() / 1000,
                    finishLoadTime: Date.now() / 1000,
                    firstPaintAfterLoadTime: 0,
                    firstPaintTime: Date.now() / 1000 - Math.random(),
                    navigationType: 'Other',
                    npnNegotiatedProtocol: 'unknown',
                    requestTime: Date.now() / 1000 - Math.random() * 3,
                    startLoadTime: Date.now() / 1000 - Math.random() * 2,
                    wasAlternateProtocolAvailable: false,
                    wasFetchedViaSpdy: false,
                    wasNpnNegotiated: false
                };
            },
            csi: function() {
                return { onloadT: Date.now(), pageT: Math.random() * 5000, startE: Date.now() - 1000, tran: 15 };
            }
        };
    }

    // 6. Permissions API
    try {
        const origQuery = window.navigator.permissions.query.bind(navigator.permissions);
        window.navigator.permissions.__proto__.query = function(parameters) {
            if (parameters.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission, onchange: null });
            }
            return origQuery(parameters);
        };
    } catch(e) {}

    // 7. WebGL — реалистичные значения
    try {
        const getParam = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParam.call(this, parameter);
        };
        const getParam2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParam2.call(this, parameter);
        };
    } catch(e) {}

    // 8. Hardware concurrency
    try {
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8,
            configurable: true
        });
    } catch(e) {}

    // 9. deviceMemory
    try {
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8,
            configurable: true
        });
    } catch(e) {}

    // 10. Platform
    try {
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32',
            configurable: true
        });
    } catch(e) {}

    // 11. Connection
    try {
        Object.defineProperty(navigator, 'connection', {
            get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }),
            configurable: true
        });
    } catch(e) {}

    // 12. Скрываем что это Playwright/automation через toString
    try {
        const origToString = Function.prototype.toString;
        const patchedFns = new WeakSet();
        Function.prototype.toString = function() {
            if (patchedFns.has(this)) {
                return 'function () { [native code] }';
            }
            return origToString.call(this);
        };
    } catch(e) {}

    // 13. Убираем document.documentElement.webdriver
    try {
        Object.defineProperty(document.documentElement, 'webdriver', {
            get: () => undefined,
            configurable: true,
            enumerable: false
        });
    } catch(e) {}

})();
"""


async def test_stealth():
    print("=" * 60)
    print("ПРЯМОЙ ТЕСТ STEALTH БРАУЗЕРА")
    print("=" * 60)

    screenshots_dir = Path("screenshots")
    screenshots_dir.mkdir(exist_ok=True)

    ua = random.choice(USER_AGENTS)
    print(f"\n[>] User-Agent: {ua[:70]}...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                "--disable-infobars",
                "--start-maximized",
                "--window-size=1280,900",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=ua,
            locale="en-US",
            timezone_id="America/New_York",
            color_scheme="light",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        # Шаг 1: context.add_init_script — выполняется для всех страниц контекста
        await context.add_init_script(FULL_STEALTH_SCRIPT)

        # Шаг 2: создаём страницу
        page = await context.new_page()

        # Шаг 3: playwright-stealth (добавляет plugins, chrome.runtime, media codecs и т.д.)
        await stealth_async(page)

        # Шаг 4: CDP патч — ПОСЛЕ stealth_async чтобы быть последним
        webdriver_patch = """
(function() {
    try { delete Object.getPrototypeOf(navigator).webdriver; } catch(e) {}
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined, configurable: true, enumerable: false
        });
    } catch(e) {}
    ['$cdc_asdjflasutopfhvcZLmcfl_','$chrome_asyncScriptInfo',
     '__webdriver_evaluate','__selenium_evaluate','__webdriver_script_function',
     '__driver_evaluate'].forEach(function(k) {
        try { delete window[k]; } catch(e) {}
        try { Object.defineProperty(window, k, {get:function(){return undefined;}, configurable:true, enumerable:false}); } catch(e) {}
    });
})();
"""
        try:
            cdp = await context.new_cdp_session(page)
            await cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": webdriver_patch})
            await cdp.send("Runtime.evaluate", {"expression": webdriver_patch, "returnByValue": False})
            print("    [OK] CDP патч применён (addScriptToEvaluateOnNewDocument + Runtime.evaluate)")
        except Exception as e:
            print(f"    [WARN] CDP патч не применён: {e}")

        print("\n[1/3] Открываем bot.sannysoft.com...")
        try:
            await page.goto("https://bot.sannysoft.com", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            path1 = screenshots_dir / "stealth_sannysoft.png"
            await page.screenshot(path=str(path1), full_page=True)
            print(f"    Скриншот сохранён: {path1}")
        except Exception as e:
            print(f"    [ERR] {e}")

        print("\n[2/3] Проверяем значения navigator напрямую...")
        try:
            results = await page.evaluate("""() => ({
                webdriver: navigator.webdriver,
                plugins: navigator.plugins.length,
                languages: navigator.languages,
                platform: navigator.platform,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemory: navigator.deviceMemory,
                chrome: !!window.chrome,
                chromeRuntime: !!(window.chrome && window.chrome.runtime),
                userAgent: navigator.userAgent.substring(0, 80),
                cdc: !!window.$cdc_asdjflasutopfhvcZLmcfl_,
                selenium: !!window.__selenium_evaluate,
            })""")

            print()
            checks = [
                ("webdriver",         results["webdriver"] is None or results["webdriver"] is False,
                 f"= {results['webdriver']}"),
                ("plugins.length",    results["plugins"] > 0,
                 f"= {results['plugins']}"),
                ("languages",         len(results["languages"]) > 0,
                 f"= {results['languages']}"),
                ("platform",          results["platform"] == "Win32",
                 f"= {results['platform']}"),
                ("hardwareConcurrency", results["hardwareConcurrency"] >= 4,
                 f"= {results['hardwareConcurrency']}"),
                ("window.chrome",     results["chrome"],
                 f"= {results['chrome']}"),
                ("chrome.runtime",    results["chromeRuntime"],
                 f"= {results['chromeRuntime']}"),
                ("$cdc_ absent",      not results["cdc"],
                 f"= {results['cdc']}"),
                ("selenium absent",   not results["selenium"],
                 f"= {results['selenium']}"),
            ]

            all_pass = True
            for name, passed, val in checks:
                status = "[PASS]" if passed else "[FAIL]"
                if not passed:
                    all_pass = False
                print(f"    {status} {name:25s} {val}")

            print()
            if all_pass:
                print("    *** ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ — браузер выглядит как человек ***")
            else:
                print("    *** ЕСТЬ ПРОБЛЕМЫ — смотри [FAIL] выше ***")

        except Exception as e:
            print(f"    [ERR] {e}")

        print("\n[3/3] Открываем fingerprintjs.com/demo...")
        try:
            await page.goto("https://fingerprintjs.com/demo/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(4000)
            path2 = screenshots_dir / "stealth_fingerprint.png"
            await page.screenshot(path=str(path2), full_page=True)
            print(f"    Скриншот сохранён: {path2}")
        except Exception as e:
            print(f"    [ERR] {e}")

        print("\n[OK] Тест завершён. Скриншоты в папке screenshots/")
        print("     Закрываем браузер через 5 секунд...")
        await page.wait_for_timeout(5000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_stealth())

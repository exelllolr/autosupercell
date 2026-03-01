"""
КАК ЗАПУСТИТЬ:
  pip install -r requirements.txt
  playwright install chromium
  python problem.py

ПРОКСИ — два варианта:
  1) Своя строка PROXY_URL ниже (формат: http://user:password@host:port).
  2) "Наш прокси" из проекта: если PROXY_URL пустой — берётся из .env:
     PROXY_ENABLED=true + Novada (NOVADA_*) или файл proxies.txt.
     То же, что использует gologin_runner и остальное приложение.

Примеры PROXY_URL:
  http://user:pass@super.novada.pro:7777
  http://user:pass@gate.smartproxy.com:10000

Без прокси: PROXY_URL="" и в .env PROXY_ENABLED=false.
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

# Корень проекта для импорта app (наш прокси из .env)
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from playwright.async_api import async_playwright, Page

# ─── НАСТРОЙКИ — заполни перед запуском ───────────────────────────────────────

PROXY_URL = ""  # или строка прокси; если пусто — используется наш прокси из .env (Novada / proxies.txt)

# Тестовые данные — невалидные, нужны только чтобы дойти до формы
SUPERCELL_EMAIL = "test@example.com"
GOOGLE_EMAIL    = "test@gmail.com"

# ──────────────────────────────────────────────────────────────────────────────


def _parse_proxy(proxy_url: str) -> Optional[dict]:
    """Парсит строку прокси в формат Playwright."""
    if not proxy_url.strip():
        return None
    import urllib.parse
    p = urllib.parse.urlparse(proxy_url)
    result = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        result["username"] = urllib.parse.unquote(p.username)
    if p.password:
        result["password"] = urllib.parse.unquote(p.password)
    return result


def _get_proxy_from_project() -> Optional[dict]:
    """Наш прокси из настроек проекта: .env + proxy_manager (Novada / proxies.txt)."""
    try:
        from app.config import settings
        from app.core.proxy_manager import proxy_manager
        if not getattr(settings, "PROXY_ENABLED", False):
            return None
        raw = proxy_manager.get_proxy()
        if not raw or not raw.get("server"):
            return None
        return {
            "server": raw.get("server", ""),
            "username": raw.get("username") or "",
            "password": raw.get("password") or "",
        }
    except Exception:
        return None


def _get_proxy() -> Optional[dict]:
    """Прокси: сначала PROXY_URL, иначе наш прокси из проекта (.env)."""
    proxy = _parse_proxy(PROXY_URL)
    if proxy:
        return proxy
    return _get_proxy_from_project()


# ══════════════════════════════════════════════════════════════════════════════
#  ТВОЯ ЗОНА — перепиши эту функцию в solution.py
# ══════════════════════════════════════════════════════════════════════════════

async def create_browser(playwright) -> Page:
    """
    Запускает браузер и возвращает page.
    Только эту функцию нужно переписать в solution.py.

    Контракт (что ожидает наш код от возвращаемой page):
    - proxy применён ко всем вкладкам включая popup и новые page в том же context
    - navigator.webdriver == undefined
    - Supercell не блокирует вход ("unusual activity")
    - Google не блокирует вход в popup ("browser or app may not be secure")
    - Работает стабильно 3 запуска подряд
    """
    proxy = _get_proxy()
    if proxy and not proxy.get("server"):
        proxy = None

    if proxy:
        print(f"[Прокси] Запуск с нашим прокси: {proxy.get('server', '')} (user: {proxy.get('username', '') or '—'})")
    else:
        print("[Прокси] Запуск без прокси (PROXY_URL пустой и в .env прокси не настроен)")

    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(
        proxy=proxy,
        locale="en-US",   # чтобы кнопки были на английском ("Log In", не "ВХОД ID")
    )
    page = await context.new_page()
    return page


# ══════════════════════════════════════════════════════════════════════════════
#  НАША ЗОНА — имитация основного сценария покупки. Не трогай.
# ══════════════════════════════════════════════════════════════════════════════

async def run_purchase(page: Page) -> dict:
    """
    Имитирует наш сценарий покупки в браузере который вернул create_browser().
    Весь путь — Supercell → checkout → Google Pay popup — идёт в одной сессии.
    """
    results = {"barrier_1_supercell": False, "barrier_2_google_popup": False}

    # ── Барьер 1: Supercell не должен блокировать при логине ──────────────────
    # Считается пройденным ТОЛЬКО если:
    #   - Кнопка Log In найдена и нажата
    #   - Поле email появилось (значит Supercell пустил на страницу логина)
    #   - "unusual activity" не появился
    print("\n[1/2] Supercell: открываем магазин и пробуем войти...")
    try:
        await page.goto("https://store.supercell.com/brawlstars", timeout=30000)
        await page.wait_for_timeout(2000)
    except Exception as e:
        print(f"    Страница не открылась: {e}")
        await page.screenshot(path="fail_supercell.png")
        return results

    # Кнопка логина — английский и русский вариант
    login_btn_selectors = [
        'button:has-text("Log In")',
        'a:has-text("Log In")',
        'button:has-text("ВХОД")',      # русский интерфейс
        'button:has-text("Войти")',
        '[href*="login"]',
    ]
    btn_clicked = False
    for sel in login_btn_selectors:
        try:
            await page.click(sel, timeout=4000)
            btn_clicked = True
            break
        except Exception:
            continue

    if not btn_clicked:
        print("    ❌ БАРЬЕР 1: кнопка 'Log In' не найдена — страница на русском или заблокирована")
        await page.screenshot(path="fail_supercell.png")
        return results

    await page.wait_for_timeout(1500)

    # Проверяем "unusual activity" — Supercell показывает его ДО или ПОСЛЕ нажатия кнопки
    content = await page.content()
    if "unusual activity" in content.lower() or "blocked your login" in content.lower():
        print("    ❌ БАРЬЕР 1: Supercell заблокировал ('unusual activity')")
        await page.screenshot(path="fail_supercell.png")
        return results

    # Ждём поле email — это главное подтверждение что Supercell пустил нас
    email_appeared = False
    try:
        await page.wait_for_selector('input[type="email"]', timeout=8000)
        email_appeared = True
    except Exception:
        pass

    # Финальная проверка контента после ожидания
    content = await page.content()
    if "unusual activity" in content.lower() or "blocked your login" in content.lower():
        print("    ❌ БАРЬЕР 1: Supercell заблокировал ('unusual activity')")
        await page.screenshot(path="fail_supercell.png")
    elif not email_appeared:
        print("    ❌ БАРЬЕР 1: поле email не появилось — логин не начался (возможно блок или UI изменился)")
        await page.screenshot(path="fail_supercell.png")
    else:
        # Вводим email чтобы убедиться что форма рабочая
        try:
            await page.fill('input[type="email"]', SUPERCELL_EMAIL, timeout=3000)
        except Exception:
            pass
        print("    ✅ Барьер 1 пройден: Supercell пустил на страницу логина, поле email доступно")
        results["barrier_1_supercell"] = True

    # ── Барьер 2: Google не должен блокировать вход в popup ──────────────────
    # Google Pay открывается как popup из той же browser-сессии.
    # Создаём новую вкладку в том же context — точно так же как это делает Google Pay.
    print("\n[2/2] Google: открываем popup и проверяем вход...")
    popup = await page.context.new_page()
    try:
        # Таймаут 45 сек — прокси может быть медленным
        await popup.goto("https://accounts.google.com/signin",
                         timeout=45000, wait_until="domcontentloaded")
        await popup.wait_for_timeout(2000)
    except Exception as e:
        err = str(e)
        if "Timeout" in err:
            print("    ❌ БАРЬЕР 2: таймаут — прокси не пропускает Google (IP заблокирован или провайдер блочит google.com)")
        else:
            print(f"    ❌ БАРЬЕР 2: страница не открылась: {e}")
        await popup.screenshot(path="fail_google_popup.png")
        await popup.close()
        return results

    try:
        await popup.fill('input[type="email"]', GOOGLE_EMAIL, timeout=5000)
        await popup.click('#identifierNext', timeout=3000)
        await popup.wait_for_timeout(3000)
    except Exception:
        pass

    popup_url     = popup.url
    popup_content = await popup.content()
    await popup.close()

    blocked = (
        "signin/rejected"         in popup_url
        or "sorry.google.com"     in popup_url
        or "not be secure"        in popup_content
        or "Couldn't sign you in" in popup_content
        or "unusual traffic"      in popup_content
    )
    if blocked:
        print("    ❌ БАРЬЕР 2: Google заблокировал вход в popup")
        await page.screenshot(path="fail_google_popup.png")
    else:
        print("    ✅ Барьер 2 пройден: Google не заблокировал в popup")
        results["barrier_2_google_popup"] = True

    # ── Итог ──────────────────────────────────────────────────────────────────
    passed = sum(results.values())
    print("\n" + "═" * 50)
    print(f"Результат: {passed}/2 барьеров пройдено")
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    if passed < 2:
        print("Скриншоты: fail_supercell.png / fail_google_popup.png")
    print("═" * 50)
    return results


async def main():
    async with async_playwright() as p:
        page = await create_browser(p)
        try:
            await run_purchase(page)
        finally:
            await page.context.browser.close()


asyncio.run(main())

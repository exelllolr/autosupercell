"""
Модуль оплаты через Google Pay на Supercell Store (FastSpring checkout).

Реальный flow FastSpring:
1. После Checkout открывается страница FastSpring с формой оплаты
2. Форма содержит вкладки: [Card] [PayPal] [G Pay] [Amazon Pay]
3. Кликаем вкладку "G Pay" → форма переключается
4. Появляется кнопка "Place Your Order" → кликаем → открывается popup Google Pay
5. В popup: сначала экран G Pay с кнопкой "Оплатить"/Pay → кликаем → открывается sign-in Google
6. Входим в Google (email + App Password), затем при необходимости подтверждаем оплату в popup
7. Ждём "Processing Payment" → "CONGRATULATIONS PURCHASE COMPLETE"
8. Скриншот_1 в profs/
9. Переходим на /account, проверяем Purchase history, скриншот_2 в profs/
10. Проверяем Payment information, откреп ляем карты если есть
"""

import asyncio
import os
import re
import random
from datetime import datetime
from loguru import logger

from app.config import settings


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


async def _delay(page, min_ms: int = 300, max_ms: int = 800):
    await page.wait_for_timeout(random.randint(min_ms, max_ms))


async def _screenshot(page, name: str, folder: str = "screenshots") -> str:
    _ensure_dir(folder)
    path = os.path.join(folder, f"{name}.png")
    try:
        await page.screenshot(path=path, full_page=False)
        logger.info(f"Скриншот: {path}")
    except Exception as e:
        logger.debug(f"Не удалось сделать скриншот {name}: {e}")
    return path


async def _screenshot_full(page, name: str, folder: str = "screenshots") -> str:
    """Полностраничный скриншот."""
    _ensure_dir(folder)
    path = os.path.join(folder, f"{name}.png")
    try:
        await page.screenshot(path=path, full_page=True)
        logger.info(f"Скриншот (full): {path}")
    except Exception as e:
        logger.debug(f"Не удалось сделать скриншот {name}: {e}")
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 1: Найти FastSpring форму и кликнуть вкладку G Pay
# ──────────────────────────────────────────────────────────────────────────────

_GPAY_TAB_SELECTORS = [
    'button:has-text("G Pay")',
    '[role="tab"]:has-text("G Pay")',
    'li:has-text("G Pay")',
    'a:has-text("G Pay")',
    'span:has-text("G Pay")',
    'button:has-text("Google Pay")',
    '[role="tab"]:has-text("Google Pay")',
    '[data-method="googlepay"]',
    '[data-method="google_pay"]',
    '[data-payment-method="google_pay"]',
    '[data-fsc-action*="google"]',
    '[id*="googlepay"]',
    '[id*="google-pay"]',
    '[class*="googlepay"]',
    '[class*="google-pay"]',
    '[class*="GooglePay"]',
    'img[alt*="Google Pay"]',
    'img[alt*="G Pay"]',
    'button svg[title*="Google"]',
]

_GPAY_PAY_BUTTON_SELECTORS = [
    'button:has-text("Place Your Order")',
    'button:has-text("Place your order")',
    'button:has-text("Place Order")',
    '.gpay-button',
    '[class*="gpay-button"]',
    '[class*="google-pay-button"]',
    'button[aria-label*="Google Pay"]',
    '[data-testid*="google-pay"]',
    'button:has-text("Pay $")',
    'button:has-text("Pay €")',
    'button:has-text("Pay £")',
    'button:has-text("Pay with Google")',
    'button:has-text("Buy with G Pay")',
    'button:has-text("G Pay")',
    'button[type="submit"]:visible',
]


async def _try_click_in_frame(frame, selectors: list, label: str) -> bool:
    for sel in selectors:
        try:
            loc = frame.locator(sel).first
            count = await loc.count()
            if count > 0:
                visible = await loc.is_visible()
                if visible:
                    await loc.scroll_into_view_if_needed()
                    await loc.click(timeout=5000)
                    logger.info(f"{label}: {sel}")
                    return True
        except Exception:
            continue
    return False


def _get_fastspring_frames(page):
    candidates = []
    try:
        for frame in page.frames:
            url = frame.url or ""
            if "skeleton.html" in url or "sbl.onfastspring.com/sbl/" in url:
                continue
            if (
                "onfastspring.com/embedded-checkout" in url
                or "onfastspring.com" in url
                or "cloudfront.net/supercell/embedded-checkout" in url
                or "fastspring.com" in url
            ):
                candidates.append(frame)
    except Exception:
        pass
    return candidates


_FASTSPRING_IFRAME_TIMEOUT_MS = 120000


async def _wait_for_fastspring_loaded(page, timeout_ms: int = None) -> list:
    if timeout_ms is None:
        timeout_ms = _FASTSPRING_IFRAME_TIMEOUT_MS
    logger.info(f"Ожидание загрузки FastSpring checkout iframe (таймаут {timeout_ms // 1000} сек)...")
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000

    while asyncio.get_event_loop().time() < deadline:
        frames = _get_fastspring_frames(page)
        if not frames:
            logger.debug("FastSpring iframe ещё не появился, ждём...")
            await page.wait_for_timeout(2000)
            continue

        loaded = []
        for frame in frames:
            try:
                has_content = await frame.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    const inputs = document.querySelectorAll('input');
                    const price = document.body.innerText.match(/\\$[\\d.]+/);
                    return btns.length > 0 || inputs.length > 0 || price !== null;
                }""")
                if has_content:
                    loaded.append(frame)
                    logger.info(f"FastSpring iframe загружен: {frame.url[:80]}")
            except Exception:
                continue

        if loaded:
            return loaded

        logger.debug(f"FastSpring iframe найден ({len(frames)}), ждём контента...")
        await page.wait_for_timeout(2000)

    logger.warning("FastSpring iframe не загрузился за отведённое время")
    return []


async def _accept_cookies_on_page(page) -> bool:
    cookie_selectors = [
        'button:has-text("Confirm My Choices")',
        'button:has-text("Confirm my choices")',
        '[role="button"]:has-text("Confirm My Choices")',
        'button:has-text("CANCEL")',
        'button:has-text("Cancel")',
        'button:has-text("Accept All Cookies")',
        'button:has-text("Accept All")',
        'button:has-text("Accept Cookies")',
        'button:has-text("Accept")',
        'button:has-text("Agree")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        '[role="button"]:has-text("Accept All")',
        '[role="button"]:has-text("Accept")',
        '[class*="cookie"] button',
        '[class*="consent"] button',
        '[id*="cookie"] button',
    ]

    async def _try(frame) -> bool:
        for sel in cookie_selectors:
            try:
                el = await frame.query_selector(sel)
                if el and await el.is_visible():
                    await el.click(force=True)
                    logger.info(f"Cookies приняты на checkout: {sel}")
                    await page.wait_for_timeout(500)
                    return True
            except Exception:
                continue
        return False

    if await _try(page):
        return True
    for frame in page.frames:
        try:
            if await _try(frame):
                return True
        except Exception:
            continue
    return False


async def select_gpay_tab_and_pay(page, timeout_ms: int = 90000) -> bool:
    logger.info("Ищем FastSpring форму и вкладку G Pay...")

    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)
    except Exception:
        pass

    await _accept_cookies_on_page(page)
    await page.wait_for_timeout(500)
    await _screenshot(page, "gpay_checkout_start")

    loaded_frames = await _wait_for_fastspring_loaded(page)

    if not loaded_frames:
        logger.info("Проверяем главную страницу на наличие G Pay...")
        try:
            loc = page.locator('button:has-text("G Pay"), button:has-text("Google Pay")').first
            if await loc.count() > 0:
                loaded_frames = [page]
            else:
                await _screenshot(page, "fastspring_gpay_not_found")
                return False
        except Exception:
            await _screenshot(page, "fastspring_gpay_not_found")
            return False

    await _screenshot(page, "fastspring_loaded")

    tab_click_max_attempts = 4
    pay_click_attempts = [(4000, "1"), (6000, "2"), (8000, "3"), (10000, "4")]

    for frame in loaded_frames:
        logger.info(f"Ищем G Pay вкладку в iframe: {frame.url[:80]}")
        tab_clicked = False
        for attempt in range(1, tab_click_max_attempts + 1):
            tab_clicked = await _try_click_in_frame(frame, _GPAY_TAB_SELECTORS, f"Нажата вкладка G Pay (попытка {attempt}/{tab_click_max_attempts})")
            if tab_clicked:
                break
            if attempt < tab_click_max_attempts:
                await page.wait_for_timeout(3000)
                logger.debug(f"Повтор поиска вкладки G Pay через 3 сек, попытка {attempt + 1}")

        if not tab_clicked:
            logger.debug(f"G Pay вкладка не найдена в {frame.url[:60]} после {tab_click_max_attempts} попыток")
            continue

        logger.info("Вкладка G Pay выбрана, ждём появления кнопки 'Place Your Order'...")
        await page.wait_for_timeout(8000)
        await _screenshot(page, "fastspring_after_gpay_tab")

        pay_clicked = False
        for wait_after_ms, label in pay_click_attempts:
            pay_clicked = await _try_click_in_frame(frame, _GPAY_PAY_BUTTON_SELECTORS, f"Нажата кнопка Place Your Order (iframe {label})")
            if pay_clicked:
                break
            if not pay_clicked:
                pay_clicked = await _try_click_in_frame(page, _GPAY_PAY_BUTTON_SELECTORS, f"Нажата кнопка Place Your Order (main {label})")
            if pay_clicked:
                break
            logger.info(f"Кнопка оплаты не найдена, ждём {wait_after_ms // 1000} сек перед следующей попыткой...")
            await page.wait_for_timeout(wait_after_ms)
            await _screenshot(page, f"fastspring_gpay_retry_{label}")

        if pay_clicked:
            await _screenshot(page, "fastspring_gpay_pay_clicked")
            return True

        logger.warning("Кнопка оплаты после выбора G Pay не найдена после всех попыток")

    await _screenshot(page, "fastspring_gpay_not_found")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 2: Логин в Google в popup
# ──────────────────────────────────────────────────────────────────────────────

_SIGNIN_FULL_WINDOW_TIMEOUT_MS = 150000
_SIGNIN_OVERLAY_POLL_MS = 30000
_SIGNIN_POPUP_TIMEOUT_MS = 90000


def _is_google_block_page(page_text: str) -> bool:
    t = (page_text or "").lower()
    return (
        "couldn't sign you in" in t
        or "this browser or app may not be secure" in t
    )


def _url_is_signin_context(url: str) -> bool:
    u = (url or "").lower()
    if "accounts.google.com" in u or ("signin" in u and "google" in u):
        return True
    if "pay.google.com" in u:
        return True
    if "pay.fastspring.com" in u and ("googlepay" in u or "embedded-checkout" in u or "google" in u):
        return True
    return False


async def _is_google_signin_full_window(page) -> bool:
    try:
        u = (page.url or "").lower()
        if _url_is_signin_context(u):
            return True
        if "pay.fastspring.com" in u and ("googlepay" in u or "embedded-checkout" in u or "google" in u):
            return True
        if "pay.google.com" in u:
            return True
        body = (await page.evaluate("() => document.body.innerText")).lower()
        if "вход" in body and ("телефон или адрес" in body or "далее" in body):
            return True
        if "sign in" in body and ("email or phone" in body or "phone or email" in body or "next" in body):
            return True
        if "телефон или адрес эл. почты" in body or "далее" in body:
            return True
    except Exception:
        pass
    return False


async def _is_google_signin_overlay(page) -> bool:
    try:
        for frame in page.frames:
            src = (frame.url or "").lower()
            name = (getattr(frame, "name", None) or "").lower()
            if "accounts.google.com" in src:
                return True
            if "pay.google.com" in src:
                return True
            if name == "payframe":
                return True
            if "pay.fastspring.com" in src and ("googlepay" in src or "embedded-checkout" in src):
                return True
    except Exception:
        pass
    return False


def _page_has_signin_url(page) -> bool:
    try:
        return _url_is_signin_context(page.url or "")
    except Exception:
        return False


async def _get_signin_frame(page):
    try:
        for frame in page.frames:
            src = (frame.url or "").lower()
            name = (getattr(frame, "name", None) or "").lower()
            if name == "payframe":
                return frame
            if "accounts.google.com" in src or "pay.google.com" in src:
                return frame
            if "pay.fastspring.com" in src and ("googlepay" in src or "embedded-checkout" in src):
                return frame
    except Exception:
        pass
    return None


async def _wait_for_signin_frame(page, timeout_sec: int = 25):
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        frame = await _get_signin_frame(page)
        if frame is not None:
            return frame
        await asyncio.sleep(1)
    return None


async def _find_frame_with_signin_form(page, timeout_sec: int = 35):
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        try:
            for frame in page.frames:
                try:
                    url = (frame.url or "").lower()
                    name = (getattr(frame, "name", None) or "").lower()
                    if name == "payframe" or "pay.google.com" in url or "accounts.google.com" in url:
                        return frame
                    has_form = await frame.evaluate("""
                        () => {
                            const body = (document.body && document.body.innerText) ? document.body.innerText.toLowerCase() : '';
                            if (body.includes('вход') && (body.includes('телефон') || body.includes('почты') || body.includes('email')))
                                return true;
                            const input = document.querySelector('input[name="identifier"], input[placeholder*="почты"], input[placeholder*="email"], input[placeholder*="Phone"]');
                            return !!input;
                        }
                    """)
                    if has_form:
                        logger.info(f"Найден iframe с формой входа по содержимому: {frame.url[:80]}")
                        return frame
                except Exception:
                    continue
        except Exception:
            pass
        await asyncio.sleep(1)
    return None


async def _log_all_frames(page, label: str = ""):
    """Логирует все фреймы страницы для диагностики (с реальными значениями)."""
    logger.info(f"=== FRAMES {label} ===")
    try:
        for i, frame in enumerate(page.frames):
            try:
                url = frame.url or "about:blank"
                name = getattr(frame, "name", "") or ""
                count = await frame.evaluate("() => document.querySelectorAll('input').length")
                logger.info(f"  Frame {i}: name='{name}' url='{url[:120]}' | inputs={count}")
            except Exception as e:
                url = getattr(frame, "url", "") or ""
                name = getattr(frame, "name", "") or ""
                logger.info(f"  Frame {i}: name='{name}' url='{url[:80]}' | err={e}")
    except Exception as e:
        logger.warning(f"Ошибка при логировании фреймов: {e}")
    logger.info(f"=== END FRAMES ===")


async def _find_google_signin_frame_deep(page, timeout_sec: int = 45):
    """
    ГЛУБОКИЙ поиск фрейма с формой входа Google.

    Реальная структура после клика "Pay with G Pay":
        pay.fastspring.com (главное окно)
          └── payframe (pay.google.com/gp/p/ui/payframe)  — has_input=False
                └── accounts.google.com  ← форма «Вход» здесь, грузится асинхронно

    Стратегия:
    1. Сначала ищем accounts.google.com фрейм — и ЖДЁМ пока в нём появится input (до timeout_sec)
    2. Если не появился — fallback: ищем pay.google.com и payframe с input
    3. Последний fallback: любой фрейм с input[name="identifier"]
    """
    logger.info(f"Глубокий поиск signin фрейма (до {timeout_sec} сек)...")
    deadline = asyncio.get_event_loop().time() + timeout_sec

    # КЛЮЧЕВОЙ ИНСАЙТ из логов:
    # - accounts.google.com НЕ появляется как отдельный фрейм в page.frames
    # - Есть только 2 фрейма: pay.fastspring.com и pay.google.com/gp/p/ui/payframe
    # - inputs=0 в payframe через evaluate() из-за cross-origin ограничений
    # - РЕШЕНИЕ: использовать Playwright frame.locator() вместо evaluate()
    #   Playwright обходит cross-origin через DevTools Protocol напрямую

    while asyncio.get_event_loop().time() < deadline:
        try:
            all_frames = page.frames
            logger.debug(f"Всего фреймов: {len(all_frames)}")

            for frame in all_frames:
                url = (frame.url or "").lower()
                name = (getattr(frame, "name", None) or "").lower()

                # Ищем в каждом фрейме через Playwright locator (обходит cross-origin)
                is_candidate = (
                    "accounts.google.com" in url
                    or "pay.google.com" in url
                    or name == "payframe"
                    or (frame != page.main_frame and "fastspring" not in url and "supercell" not in url and "cloudfront" not in url)
                )
                if not is_candidate:
                    continue

                try:
                    # Playwright locator работает через CDP и обходит cross-origin
                    email_loc = frame.locator('input[name="identifier"], #identifierId, input[type="email"]').first
                    count = await email_loc.count()
                    if count > 0:
                        frame_url = (frame.url or "")[:100]
                        logger.info(f"Найден signin фрейм через locator: name='{name}' url='{frame_url}'")
                        return frame
                except Exception as e:
                    logger.debug(f"locator check err [{name}]: {e}")
                    continue

        except Exception as e:
            logger.debug(f"Ошибка поиска фрейма: {e}")

        await asyncio.sleep(2)

    # Fallback: возвращаем pay.google.com фрейм — туда вводить email через keyboard
    for frame in page.frames:
        url = (frame.url or "").lower()
        name = (getattr(frame, "name", None) or "").lower()
        if "pay.google.com" in url or name == "payframe":
            frame_url = (frame.url or "")[:80]
            logger.warning(f"Fallback: используем pay.google.com фрейм для ввода: {frame_url}")
            return frame

    logger.warning(f"Signin фрейм не найден за {timeout_sec} сек")
    return None


def _parse_first_backup_code(backup_codes_str: str) -> str | None:
    if not backup_codes_str or not backup_codes_str.strip():
        return None
    digits = "".join(c for c in backup_codes_str if c.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return None


async def _type_in_frame(scope, popup_page, text: str, delay_min: int = 80, delay_max: int = 180):
    """Вводит текст посимвольно — в iframe используем press_sequentially, иначе keyboard.type."""
    if scope != popup_page:
        # press_sequentially работает на ElementHandle, не на Frame
        # Используем evaluate для посимвольного ввода
        for char in text:
            try:
                await scope.evaluate(f"""
                    () => {{
                        const el = document.activeElement;
                        if (el) {{
                            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            nativeInputValueSetter.call(el, el.value + {repr(char)});
                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        }}
                    }}
                """)
            except Exception:
                pass
            await popup_page.wait_for_timeout(random.randint(delay_min, delay_max))
    else:
        await popup_page.keyboard.type(text, delay=random.randint(delay_min, delay_max))


async def _login_google_in_popup(
    popup_page, email: str, app_password: str, backup_codes: str = ""
) -> tuple[bool, str | None]:
    """
    Входит в Google в popup-окне Google Pay.
    
    АРХИТЕКТУРА (установлена через диагностику):
    - Всего 2 фрейма: pay.fastspring.com (main) и pay.google.com/gp/p/ui/payframe
    - accounts.google.com НЕ появляется как отдельный фрейм
    - Форма "Вход" рендерится ВНУТРИ payframe (pay.google.com)
    - frame.evaluate() не работает в payframe из-за cross-origin
    - РЕШЕНИЕ: page.frame_locator('iframe[src*="pay.google.com"]') обходит cross-origin
    """
    logger.info("Вход в Google в popup окне...")

    try:
        await popup_page.wait_for_load_state("domcontentloaded", timeout=60000)
    except Exception:
        pass

    current_url = popup_page.url or ""
    logger.info(f"URL окна Google: {current_url[:80]}")

    is_full_window = await _is_google_signin_full_window(popup_page)
    if not _url_is_signin_context(current_url) and not is_full_window:
        logger.info("Google логин не требуется (уже залогинен или другая страница)")
        return True, None

    await _screenshot(popup_page, "google_login_popup")

    # Проверка блокировки
    try:
        body_text = await popup_page.evaluate("() => document.body.innerText")
        if _is_google_block_page(body_text):
            msg = "Google: «This browser or app may not be secure». Войдите вручную в том же Chrome-профиле."
            logger.warning(msg)
            return False, msg
    except Exception:
        pass

    type_delay_min, type_delay_max = 80, 180

    # Popup «Sign in - Google Accounts» (accounts.google.com): форма на основной странице, iframe не нужен
    use_main_page_only = "accounts.google.com" in (current_url or "").lower()
    if use_main_page_only:
        logger.info("Окно accounts.google.com — форма входа на основной странице (без iframe)")

    # ── frame_locator на payframe (pay.google.com) — только если НЕ popup accounts.google.com ───────
    await _log_all_frames(popup_page, "НАЧАЛО ЛОГИНА")

    if not use_main_page_only:
        # Ждём появления iframe (форма в том же окне pay.fastspring после "Pay with G Pay")
        try:
            await popup_page.wait_for_selector(
                'iframe[name="payframe"], iframe[src*="pay.google.com"]',
                state="attached",
                timeout=45000,
            )
            logger.info("iframe payframe / pay.google.com появился")
        except Exception as e:
            logger.warning("Ожидание iframe payframe: %s", e)
    await popup_page.wait_for_timeout(2000)

    # Кандидаты: name=payframe (приоритет), src с pay.google.com, вложенный iframe
    gpay_fl = None
    gpay_fl_candidates = [
        popup_page.frame_locator('iframe[name="payframe"]'),
        popup_page.frame_locator('iframe[src*="pay.google.com"]'),
        popup_page.frame_locator('iframe[src*="payframe"]'),
        popup_page.frame_locator('iframe').first,
    ]
    # Форма «Вход» может быть во вложенном iframe внутри payframe
    try:
        gpay_fl_candidates.append(
            popup_page.frame_locator('iframe[name="payframe"]').frame_locator('iframe').first
        )
    except Exception:
        pass
    try:
        gpay_fl_candidates.append(
            popup_page.frame_locator('iframe[src*="pay.google.com"]').frame_locator('iframe').first
        )
    except Exception:
        pass

    email_selectors = [
        'input[name="identifier"]',
        '#identifierId',
        'input[type="email"]',
        'input[placeholder*="почты"]',
        'input[placeholder*="Phone or email"]',
        'input[placeholder*="Email or phone"]',
        'input[aria-label*="email"]',
        'input[type="text"]',
    ]

    # ── Ввод email ────────────────────────────────────────────────────────────
    email_entered = False
    placeholders = ["Телефон или адрес эл. почты", "Phone or email", "Email or phone"]

    # Popup accounts.google.com: форма на основной странице — пробуем сразу
    if use_main_page_only:
        logger.info("Поиск поля email на основной странице (accounts.google.com)...")
        for sel in email_selectors:
            try:
                loc = popup_page.locator(sel).first
                await loc.wait_for(state="visible", timeout=5000)
                await loc.click(timeout=10000)
                await _delay(popup_page, 400, 700)
                await loc.press_sequentially(email, delay=random.randint(type_delay_min, type_delay_max))
                await _delay(popup_page, 400, 700)
                email_entered = True
                logger.info("Email введён на основной странице (selector: %s)", sel)
                break
            except Exception:
                continue
        if not email_entered:
            for ph in placeholders:
                try:
                    loc = popup_page.get_by_placeholder(ph).first
                    await loc.wait_for(state="visible", timeout=5000)
                    await loc.click(timeout=10000)
                    await _delay(popup_page, 400, 700)
                    await loc.press_sequentially(email, delay=random.randint(type_delay_min, type_delay_max))
                    await _delay(popup_page, 400, 700)
                    email_entered = True
                    logger.info("Email введён по placeholder: %s", ph[:30])
                    break
                except Exception:
                    continue

    logger.info("Ожидание поля email в payframe (до 50 сек)...")
    for wait_attempt in range(50):
        if email_entered:
            break
        for fl_candidate in gpay_fl_candidates:
            try:
                for sel in email_selectors:
                    try:
                        loc = fl_candidate.locator(sel).first
                        await loc.wait_for(state="visible", timeout=3000)
                        await loc.click(timeout=10000)
                        await _delay(popup_page, 400, 700)
                        await loc.press_sequentially(email, delay=random.randint(type_delay_min, type_delay_max))
                        await _delay(popup_page, 400, 700)
                        email_entered = True
                        gpay_fl = fl_candidate
                        logger.info("Email введён через frame_locator: %s", sel)
                        break
                    except Exception:
                        continue
                if email_entered:
                    break
                for ph in placeholders:
                    try:
                        loc = fl_candidate.get_by_placeholder(ph).first
                        await loc.wait_for(state="visible", timeout=3000)
                        await loc.click(timeout=10000)
                        await _delay(popup_page, 400, 700)
                        await loc.press_sequentially(email, delay=random.randint(type_delay_min, type_delay_max))
                        await _delay(popup_page, 400, 700)
                        email_entered = True
                        gpay_fl = fl_candidate
                        logger.info("Поле email введено через get_by_placeholder: %s", ph[:30])
                        break
                    except Exception:
                        continue
            except Exception as e:
                logger.debug("frame_locator попытка: %s", e)
            if email_entered:
                break
        if email_entered:
            break
        await popup_page.wait_for_timeout(1000)
    
    # Fallback: keyboard.type после клика по координатам поля
    if not email_entered:
        logger.warning("frame_locator не нашёл поле email, пробуем keyboard fallback...")
        try:
            # Кликаем в центр payframe и вводим через keyboard
            for frame in popup_page.frames:
                if "pay.google.com" in (frame.url or ""):
                    # Получаем bounding box iframe элемента
                    iframe_el = await frame.frame_element()
                    bbox = await iframe_el.bounding_box()
                    if bbox:
                        # Кликаем в правую часть (поле email)
                        click_x = bbox["x"] + bbox["width"] * 0.7
                        click_y = bbox["y"] + bbox["height"] * 0.35
                        await popup_page.mouse.click(click_x, click_y)
                        await popup_page.wait_for_timeout(500)
                        await popup_page.keyboard.type(email, delay=random.randint(type_delay_min, type_delay_max))
                        email_entered = True
                        logger.info(f"Email введён через mouse.click + keyboard.type (bbox: {bbox})")
                        break
        except Exception as e:
            logger.debug(f"keyboard fallback: {e}")

    # JS fallback через основную страницу
    if not email_entered:
        logger.info("JS fallback через основную страницу...")
        try:
            js_ok = await popup_page.evaluate("""
                (email) => {
                    const sel = 'input[name="identifier"], input[type="email"], #identifierId';
                    const input = document.querySelector(sel);
                    if (!input) return false;
                    input.focus();
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                    setter.call(input, email);
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                    return true;
                }
            """, email)
            if js_ok:
                email_entered = True
                logger.info("Email введён (JS fallback на основной странице)")
        except Exception as e:
            logger.debug(f"JS fallback: {e}")

    if not email_entered:
        logger.warning("Поле email не найдено ни одним методом")
        await _log_all_frames(popup_page, "EMAIL НЕ НАЙДЕН")
        return False, "Поле email не найдено"

    await _delay(popup_page, 600, 1200)

    # ── Кнопка «Далее» / Next ─────────────────────────────────────────────────
    next_clicked = False
    next_selectors = [
        '#identifierNext',
        'button:has-text("Далее")',
        'button:has-text("Next")',
        '[role="button"]:has-text("Далее")',
        '[role="button"]:has-text("Next")',
        'button[type="submit"]',
    ]
    
    # Через frame_locator (если нашли)
    if gpay_fl:
        for sel in next_selectors:
            try:
                loc = gpay_fl.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=10000)
                    next_clicked = True
                    logger.info(f"Next нажат через frame_locator: {sel}")
                    break
            except Exception:
                continue

    # Через основную страницу
    if not next_clicked:
        for fl in gpay_fl_candidates:
            for sel in next_selectors:
                try:
                    loc = fl.locator(sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=8000)
                        next_clicked = True
                        logger.info(f"Next нажат (fallback fl): {sel}")
                        break
                except Exception:
                    continue
            if next_clicked:
                break

    if not next_clicked:
        # Enter как последний вариант
        await popup_page.keyboard.press("Enter")
        next_clicked = True
        logger.info("Next нажат через Enter")

    await popup_page.wait_for_timeout(6000)

    # Проверка блокировки
    try:
        body_text = await popup_page.evaluate("() => document.body.innerText")
        if _is_google_block_page(body_text):
            msg = "Google заблокировал вход. Залогиньтесь вручную в том же Chrome-профиле."
            logger.warning(msg)
            return False, msg
    except Exception:
        pass

    # ── Ввод пароля ────────────────────────────────────────────────────────────
    pw_selectors = [
        'input[type="password"]',
        'input[name="password"]',
        '#password input',
        'input[aria-label*="пароль"]',
        'input[aria-label*="password"]',
    ]
    pw_entered = False
    password_clean = app_password.replace(" ", "")

    logger.info("Ожидание поля пароля (до 45 сек)...")
    for wait_attempt in range(45):
        # Через frame_locator
        candidates = [gpay_fl] + gpay_fl_candidates if gpay_fl else gpay_fl_candidates
        for fl in candidates:
            if fl is None:
                continue
            for sel in pw_selectors:
                try:
                    loc = fl.locator(sel).first
                    cnt = await loc.count()
                    if cnt > 0:
                        await loc.click(timeout=8000)
                        await _delay(popup_page, 400, 700)
                        await loc.press_sequentially(password_clean, delay=random.randint(type_delay_min, type_delay_max))
                        await _delay(popup_page, 400, 700)
                        pw_entered = True
                        logger.info(f"Пароль введён через frame_locator ({sel})")
                        break
                except Exception as e:
                    logger.debug(f"pw frame_locator {sel}: {e}")
                    continue
            if pw_entered:
                break
        if pw_entered:
            break
        await popup_page.wait_for_timeout(1000)

    # Keyboard fallback для пароля
    if not pw_entered:
        try:
            for frame in popup_page.frames:
                if "pay.google.com" in (frame.url or ""):
                    iframe_el = await frame.frame_element()
                    bbox = await iframe_el.bounding_box()
                    if bbox:
                        click_x = bbox["x"] + bbox["width"] * 0.7
                        click_y = bbox["y"] + bbox["height"] * 0.4
                        await popup_page.mouse.click(click_x, click_y)
                        await popup_page.wait_for_timeout(500)
                        await popup_page.keyboard.type(password_clean, delay=random.randint(type_delay_min, type_delay_max))
                        pw_entered = True
                        logger.info("Пароль введён через mouse.click + keyboard.type")
                        break
        except Exception as e:
            logger.debug(f"pw keyboard fallback: {e}")

    if not pw_entered:
        logger.warning("Поле пароля не найдено")
        return False, "Поле пароля не найдено"

    await _delay(popup_page, 600, 1200)

    # Next после пароля
    for candidates in ([gpay_fl] + gpay_fl_candidates if gpay_fl else gpay_fl_candidates):
        if candidates is None:
            continue
        for sel in ['#passwordNext', 'button:has-text("Next")', 'button:has-text("Далее")', 'button[type="submit"]']:
            try:
                loc = candidates.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=10000)
                    logger.info(f"Next после пароля: {sel}")
                    break
            except Exception:
                continue
        else:
            continue
        break
    else:
        await popup_page.keyboard.press("Enter")
        logger.info("Next после пароля через Enter")

    await popup_page.wait_for_timeout(8000)

    # ── 2-Step Verification (если есть) ──────────────────────────────────────
    backup_code = _parse_first_backup_code(backup_codes)
    if backup_code:
        try:
            body_text = (await popup_page.evaluate("() => document.body.innerText")).lower()
            current_url = (popup_page.url or "").lower()
            is_2sv = (
                "challenge" in current_url
                or "2-step" in body_text
                or "sent a notification" in body_text
                or "open the" in body_text
            )
            if is_2sv:
                logger.info("2-Step Verification, ищем «Try another way»...")
                fl_list = ([gpay_fl] + gpay_fl_candidates) if gpay_fl else gpay_fl_candidates
                for fl in fl_list:
                    if fl is None:
                        continue
                    for sel in ['a:has-text("Try another way")', 'span:has-text("Try another way")', '[role="link"]:has-text("Try another way")']:
                        try:
                            loc = fl.locator(sel).first
                            if await loc.count() > 0:
                                await loc.click(timeout=10000)
                                logger.info("Нажато «Try another way»")
                                break
                        except Exception:
                            continue
                await popup_page.wait_for_timeout(10000)

                for fl in fl_list:
                    if fl is None:
                        continue
                    for sel in ['a:has-text("8-digit backup")', 'div:has-text("8-digit backup")', 'a:has-text("backup code")', 'span:has-text("backup code")']:
                        try:
                            loc = fl.locator(sel).first
                            if await loc.count() > 0:
                                await loc.click(timeout=10000)
                                logger.info(f"Выбран вход по резервному коду: {sel}")
                                break
                        except Exception:
                            continue
                await popup_page.wait_for_timeout(6000)

                for fl in fl_list:
                    if fl is None:
                        continue
                    for sel in ['input[type="tel"]', 'input[name="backupCode"]', 'input[type="text"]']:
                        try:
                            loc = fl.locator(sel).first
                            if await loc.count() > 0:
                                await loc.click(timeout=8000)
                                await loc.press_sequentially(backup_code, delay=random.randint(type_delay_min, type_delay_max))
                                logger.info("Введён резервный код")
                                await popup_page.wait_for_timeout(1000)
                                await popup_page.keyboard.press("Enter")
                                await popup_page.wait_for_timeout(6000)
                                break
                        except Exception:
                            continue
        except Exception as e:
            logger.debug(f"2SV: {e}")

    try:
        await popup_page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        await popup_page.wait_for_timeout(10000)

    try:
        body_text = await popup_page.evaluate("() => document.body.innerText")
        if _is_google_block_page(body_text):
            msg = "Google заблокировал вход после пароля. Залогиньтесь вручную."
            logger.warning(msg)
            return False, msg
    except Exception:
        pass

    logger.info(f"После логина URL: {popup_page.url}")
    await _screenshot(popup_page, "google_login_done")
    return True, None


_PAY_WITH_GPAY_SELECTORS = [
    'button:has-text("Pay with G Pay")',
    'button:has-text("Pay with Google Pay")',
    'button:has-text("Pay with")',
    '[role="button"]:has-text("Pay with G Pay")',
    '[role="button"]:has-text("Pay with Google Pay")',
    '[role="button"]:has-text("Pay with")',
    'a:has-text("Pay with G Pay")',
    'a:has-text("Pay with Google Pay")',
    'div[role="button"]:has-text("Pay with")',
    '[class*="gpay"]:has-text("Pay with")',
    '[class*="google-pay"]:has-text("Pay with")',
    '[class*="pay-button"]',
    '[class*="payButton"]',
]


async def _click_pay_with_gpay_in_popup(popup_page) -> bool:
    """Нажимает «Pay with G Pay» в popup — после этого открывается Sign-in."""
    logger.info("Ожидание и клик по кнопке 'Pay with G Pay' в popup...")
    try:
        await popup_page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass
    await popup_page.wait_for_timeout(8000)
    try:
        await popup_page.wait_for_selector(
            'button:has-text("Pay with"), [role="button"]:has-text("Pay with")',
            timeout=20000,
        )
    except Exception:
        pass

    async def _try_click(scope, label: str) -> bool:
        for sel in _PAY_WITH_GPAY_SELECTORS:
            try:
                loc = scope.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.scroll_into_view_if_needed()
                    await _delay(popup_page, 400, 800)
                    await loc.click(timeout=15000)
                    logger.info(f"Нажата кнопка 'Pay with G Pay' ({label}): {sel[:50]}")
                    return True
            except Exception:
                continue
        return False

    if await _try_click(popup_page, "основная страница"):
        return True

    for text in ["Pay with G Pay", "Pay with Google Pay", "Pay with"]:
        try:
            el = popup_page.get_by_text(text, exact=False).first
            if await el.count() > 0 and await el.is_visible():
                await el.scroll_into_view_if_needed()
                await _delay(popup_page, 400, 800)
                await el.click(timeout=15000)
                logger.info(f"Нажата 'Pay with G Pay' (get_by_text: '{text}')")
                return True
        except Exception:
            continue

    try:
        btn = popup_page.get_by_role("button", name=re.compile(r"pay with", re.I))
        if await btn.count() > 0 and await btn.first.is_visible():
            await btn.first.scroll_into_view_if_needed()
            await _delay(popup_page, 400, 800)
            await btn.first.click(timeout=15000)
            logger.info("Нажата 'Pay with G Pay' (get_by_role)")
            return True
    except Exception:
        pass

    try:
        clicked = await popup_page.evaluate("""
            () => {
                const texts = ['Pay with G Pay', 'Pay with Google Pay', 'Pay with'];
                const all = document.querySelectorAll('button, a, [role="button"], div[class*="pay"], div[class*="button"]');
                for (const el of all) {
                    const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (texts.some(s => t.includes(s))) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if clicked:
            logger.info("Нажата 'Pay with G Pay' (JS click)")
            return True
    except Exception:
        pass

    for frame in popup_page.frames:
        if frame == popup_page.main_frame:
            continue
        try:
            if await _try_click(frame, "iframe"):
                return True
        except Exception:
            continue

    logger.warning("Кнопка 'Pay with G Pay' не найдена в popup")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 3: Подтверждение оплаты в popup Google Pay
# ──────────────────────────────────────────────────────────────────────────────

async def _confirm_payment_in_popup(popup_page) -> bool:
    logger.info("Подтверждение оплаты в Google Pay popup...")

    try:
        await popup_page.wait_for_load_state("domcontentloaded", timeout=60000)
    except Exception:
        pass

    await popup_page.wait_for_timeout(6000)
    await _screenshot(popup_page, "google_pay_confirm_popup")

    confirm_selectors = [
        'button:has-text("Pay with G Pay")',
        'button:has-text("Pay with Google Pay")',
        '[role="button"]:has-text("Pay with G Pay")',
        '[role="button"]:has-text("Pay with Google Pay")',
        'button:has-text("Оплатить")',
        'a:has-text("Оплатить")',
        '[role="button"]:has-text("Оплатить")',
        'button:has-text("Pay")',
        'button:has-text("Continue")',
        'button:has-text("Confirm")',
        'button:has-text("Place order")',
        'button:has-text("Buy")',
        '[class*="pay-button"]',
        '[class*="payButton"]',
        '[class*="confirm"]',
        'button[type="submit"]',
    ]

    for sel in confirm_selectors:
        try:
            loc = popup_page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.scroll_into_view_if_needed()
                await _delay(popup_page, 800, 1500)
                await loc.click(timeout=15000)
                logger.info(f"Оплата подтверждена: {sel}")
                return True
        except Exception:
            continue

    logger.warning("Кнопка подтверждения оплаты не найдена")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 4: Ожидание Processing Payment → CONGRATULATIONS
# ──────────────────────────────────────────────────────────────────────────────

async def _wait_for_purchase_complete(page, timeout_ms: int = 120000) -> bool:
    logger.info("Ожидание Processing Payment...")
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    processing_seen = False
    complete_seen = False

    while asyncio.get_event_loop().time() < deadline:
        try:
            url = (page.url or "").lower()
            text = (await page.evaluate("() => document.body.innerText")).lower()

            if not processing_seen and ("processing" in text or "processing payment" in text or "processing" in url):
                processing_seen = True
                logger.info("Страница 'Processing Payment' обнаружена")
                await _screenshot(page, "processing_payment")

            success_phrases = [
                "congratulations", "purchase complete", "order complete",
                "thank you", "order confirmed", "payment successful",
                "purchase successful", "payment complete",
            ]
            success_urls = ["/success", "/thank-you", "/order-confirmed", "/complete", "/receipt", "/confirmation"]

            for phrase in success_phrases:
                if phrase in text:
                    complete_seen = True
                    logger.info(f"Страница успеха: '{phrase}'")
                    break
            for u in success_urls:
                if u in url:
                    complete_seen = True
                    logger.info(f"URL успеха: '{url}'")
                    break
            if complete_seen:
                return True
        except Exception:
            pass
        await page.wait_for_timeout(2000)

    logger.warning("Страница успеха не появилась за отведённое время")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 5: Скриншот в profs/
# ──────────────────────────────────────────────────────────────────────────────

async def _take_proof_screenshot(page, name: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{name}_{ts}"
    path = await _screenshot_full(page, filename, folder="profs")
    logger.info(f"Proof скриншот: {path}")
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 6: Проверка /account
# ──────────────────────────────────────────────────────────────────────────────

async def _check_account_and_cleanup(browser, product_name: str = "") -> dict:
    page = browser.page
    result = {"purchase_verified": False, "screenshot_account": None, "cards_removed": 0}

    try:
        logger.info("Переход на страницу аккаунта: https://store.supercell.com/account")
        await page.goto("https://store.supercell.com/account", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        for sel in ['text="Purchase history"', ':has-text("Purchase history")', 'h2:has-text("Purchase")', 'h3:has-text("Purchase")']:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed()
                    await page.wait_for_timeout(1000)
                    logger.info(f"Purchase history найдена: {sel}")
                    break
            except Exception:
                continue

        try:
            page_text = (await page.evaluate("() => document.body.innerText")).lower()
            if product_name and product_name.lower() in page_text:
                result["purchase_verified"] = True
                logger.info(f"Покупка '{product_name}' найдена в Purchase history")
            elif "gem" in page_text or "brawl" in page_text:
                result["purchase_verified"] = True
                logger.info("Покупка найдена в Purchase history (по ключевым словам)")
        except Exception:
            pass

        result["screenshot_account"] = await _take_proof_screenshot(page, "purchase_history")

        for sel in ['text="Payment information"', ':has-text("Payment information")', 'h2:has-text("Payment")', 'h3:has-text("Payment")']:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed()
                    await page.wait_for_timeout(1000)
                    logger.info(f"Payment information найдена: {sel}")
                    break
            except Exception:
                continue

        await _screenshot(page, "payment_information_section")

        remove_selectors = [
            'button:has-text("Отвязать способ оплаты")',
            'button:has-text("Отвязать")',
            'button:has-text("Remove")',
            'button:has-text("Delete")',
            'button:has-text("Unlink")',
            'a:has-text("Remove")',
            '[class*="remove"]:visible',
            '[class*="delete"]:visible',
        ]
        cards_removed = 0
        for _ in range(10):
            removed_this_round = False
            for sel in remove_selectors:
                try:
                    locs = page.locator(sel)
                    if await locs.count() > 0:
                        loc = locs.first
                        if await loc.is_visible():
                            await loc.scroll_into_view_if_needed()
                            await page.wait_for_timeout(500)
                            await loc.click(timeout=5000)
                            cards_removed += 1
                            removed_this_round = True
                            await page.wait_for_timeout(2000)
                            for confirm_sel in ['button:has-text("Confirm")', 'button:has-text("Yes")', 'button:has-text("Да")']:
                                try:
                                    conf = page.locator(confirm_sel).first
                                    if await conf.count() > 0 and await conf.is_visible():
                                        await conf.click(timeout=3000)
                                        await page.wait_for_timeout(1500)
                                except Exception:
                                    pass
                            break
                except Exception:
                    continue
            if not removed_this_round:
                break

        result["cards_removed"] = cards_removed
        if cards_removed > 0:
            logger.info(f"Удалено карт: {cards_removed}")
        else:
            logger.info("Привязанных карт не найдено")

    except Exception as e:
        logger.error(f"Ошибка при проверке аккаунта: {e}")

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 7: Выход из Google
# ──────────────────────────────────────────────────────────────────────────────

async def _logout_google(browser) -> None:
    logger.info("Выход из Google (очистка cookies)...")
    try:
        if browser.context:
            cookies = await browser.context.cookies()
            google_cookies = [c for c in cookies if "google" in c.get("domain", "")]
            if google_cookies:
                await browser.context.clear_cookies()
                logger.info(f"Очищено {len(google_cookies)} Google cookies")
            else:
                logger.info("Google cookies не найдены")
    except Exception as e:
        logger.warning(f"Ошибка при выходе из Google: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Главная функция
# ──────────────────────────────────────────────────────────────────────────────

async def handle_google_pay(
    browser,
    email: str,
    app_password: str,
    payment_timeout: int = 300,
    product_name: str = "",
) -> dict:
    """Полный flow оплаты через Google Pay (FastSpring checkout)."""
    result = {
        "success": False,
        "google_pay_clicked": False,
        "payment_confirmed": False,
        "payment_verified": False,
        "screenshot_success": None,
        "screenshot_account": None,
        "cards_removed": 0,
        "error": None,
    }

    page = browser.page
    if not page:
        result["error"] = "Страница браузера не инициализирована"
        return result

    try:
        logger.info(f"Google Pay flow начат. URL: {page.url}")
        await _screenshot(page, "gpay_start")

        # ── Шаг 1: Кликнуть G Pay вкладку и Place Your Order ──────────────────
        popup_page = None
        clicked = False
        try:
            async with page.context.expect_page(timeout=_SIGNIN_FULL_WINDOW_TIMEOUT_MS) as popup_info:
                clicked = await select_gpay_tab_and_pay(page, timeout_ms=180000)
            if clicked:
                popup_page = await popup_info.value
                logger.info(f"Открылось окно Google Pay: {popup_page.url}")
        except Exception as e:
            logger.info(f"Окно не открылось или таймаут ({type(e).__name__})")

        if not clicked:
            result["error"] = "Не удалось кликнуть G Pay вкладку или Place Your Order"
            await _screenshot(page, "gpay_click_failed")
            return result

        result["google_pay_clicked"] = True
        await page.wait_for_timeout(2000)

        # ── Поиск страницы авторизации ─────────────────────────────────────────
        auth_page = None
        if browser.context:
            poll_sec = min(60, _SIGNIN_FULL_WINDOW_TIMEOUT_MS // 1000)
            for _ in range(poll_sec):
                await asyncio.sleep(1)
                for p in browser.context.pages:
                    if p == page:
                        continue
                    try:
                        if await _is_google_signin_full_window(p):
                            auth_page = p
                            logger.info(f"Найдено полное окно входа Google (приоритет 1): {(p.url or '')[:80]}")
                            break
                    except Exception:
                        continue
                if auth_page is not None:
                    break
            if auth_page is None:
                for p in browser.context.pages:
                    if p == page:
                        continue
                    try:
                        if await _is_google_signin_overlay(p):
                            auth_page = p
                            logger.info(f"Найден оверлей входа Google (приоритет 2): {(p.url or '')[:80]}")
                            break
                    except Exception:
                        continue
            if auth_page is None and popup_page:
                auth_page = popup_page
                logger.info(f"Используется popup (приоритет 3): {(popup_page.url or '')[:80]}")

        popup_page = auth_page if auth_page else popup_page
        target_page = popup_page if popup_page else page

        if popup_page:
            try:
                await popup_page.wait_for_load_state("domcontentloaded", timeout=90000)
            except Exception:
                pass

            # В popup нажимаем «Pay with G Pay» — после этого может открыться:
            # 1) Отдельное POPUP-окно "Sign in - Google Accounts" (accounts.google.com) — приоритет
            # 2) Форма входа в том же окне во iframe (payframe / pay.google.com)
            pay_with_gpay_clicked = await _click_pay_with_gpay_in_popup(popup_page)
            if pay_with_gpay_clicked:
                await popup_page.wait_for_timeout(5000)
                # Приоритет 1: ищем отдельное popup-окно Sign in (accounts.google.com) — как на скриншоте
                logger.info("Ожидание popup «Sign in - Google Accounts» (accounts.google.com, до 45 сек)...")
                signin_popup = None
                for _ in range(45):
                    await popup_page.wait_for_timeout(1000)
                    if browser.context:
                        for p in browser.context.pages:
                            if p == page:
                                continue
                            try:
                                u = (p.url or "").lower()
                                if "accounts.google.com" in u or ("signin" in u and "google" in u):
                                    signin_popup = p
                                    logger.info("Найден popup Sign in: %s", (p.url or "")[:80])
                                    break
                            except Exception:
                                pass
                    if signin_popup:
                        popup_page = signin_popup
                        target_page = signin_popup
                        await popup_page.wait_for_load_state("domcontentloaded", timeout=30000)
                        await popup_page.wait_for_timeout(2000)
                        break

                if not signin_popup:
                    # Приоритет 2: форма в том же окне во iframe (payframe / pay.google.com)
                    logger.info("Popup accounts.google.com не открылся, ожидание iframe payframe (до 15 сек)...")
                    for _ in range(15):
                        await popup_page.wait_for_timeout(1000)
                        try:
                            for f in popup_page.frames:
                                url = (f.url or "").lower()
                                name = (getattr(f, "name", None) or "").lower()
                                if name == "payframe" or "pay.google.com" in url or "accounts.google.com" in url:
                                    logger.info("Найден iframe с формой входа: name=%s url=%s", name, url[:70])
                                    await popup_page.wait_for_timeout(2000)
                                    break
                            else:
                                continue
                            break
                        except Exception:
                            pass

            await _log_all_frames(popup_page, "ПОСЛЕ КЛИКА Pay with G Pay")

            current_url = (popup_page.url or "").lower()
            # Sign-in: popup accounts.google.com ИЛИ форма в том же окне (iframe payframe / pay.fastspring googlepay)
            is_signin = (
                "accounts.google.com" in current_url
                or _url_is_signin_context(current_url)
                or await _is_google_signin_full_window(popup_page)
                or ("pay.fastspring.com" in current_url and "googlepay" in current_url)
            )
            signin_page = None
            if is_signin:
                signin_page = popup_page
                if "accounts.google.com" in current_url:
                    logger.info("Окно Sign in (popup accounts.google.com), переходим к логину")
                else:
                    logger.info("Форма входа в этом окне (iframe/ pay.fastspring), переходим к логину")
            if not is_signin:
                logger.info("Окно на экране G Pay, нажимаем 'Оплатить' / Pay...")
                first_pay_clicked = await _confirm_payment_in_popup(popup_page)
                if first_pay_clicked:
                    logger.info("Ожидание страницы входа Google (до 90 сек)...")
                    for _ in range(90):
                        await popup_page.wait_for_timeout(1000)
                        try:
                            if await _is_google_signin_full_window(popup_page):
                                signin_page = popup_page
                                logger.info("Страница входа в том же окне")
                                break
                            current_url = (popup_page.url or "").lower()
                            if "accounts.google.com" in current_url or "signin" in current_url:
                                signin_page = popup_page
                                break
                        except Exception:
                            pass
                        if signin_page is None and browser.context:
                            for p in browser.context.pages:
                                if p == page:
                                    continue
                                try:
                                    if await _is_google_signin_full_window(p) or _page_has_signin_url(p):
                                        signin_page = p
                                        logger.info(f"Страница входа в новом окне: {(p.url or '')[:80]}")
                                        break
                                except Exception:
                                    continue
                        if signin_page is not None:
                            break

            if signin_page is None and popup_page:
                try:
                    if await _is_google_signin_full_window(popup_page) or _page_has_signin_url(popup_page):
                        signin_page = popup_page
                except Exception:
                    pass

            # ── Логин в Google ─────────────────────────────────────────────────
            if (signin_page or popup_page) and email and app_password:
                login_page = signin_page or popup_page
                try:
                    target_url = (login_page.url or "").lower()
                    need_login = (
                        _url_is_signin_context(target_url)
                        or await _is_google_signin_full_window(login_page)
                    )
                    if "pay.fastspring.com" in target_url and "googlepay" in target_url:
                        need_login = True
                    if need_login:
                        logger.info(f"Запуск входа в Google: {(login_page.url or '')[:90]}")
                        backup_codes = getattr(settings, "GOOGLE_BACKUP_CODES", "") or ""
                        try:
                            logged_in, login_msg = await _login_google_in_popup(
                                login_page, email, app_password, backup_codes=backup_codes
                            )
                            if not logged_in:
                                result["error"] = login_msg or "Не удалось войти в Google"
                            else:
                                await asyncio.sleep(5)
                        except Exception as e:
                            logger.warning(f"Ошибка при входе в Google: {e}")
                            result["error"] = str(e)
                    else:
                        logger.info(f"Sign-in не открылся. URL: {login_page.url}")
                except Exception as e:
                    logger.warning(f"Ошибка при входе в Google: {e}")

            target_page = signin_page if signin_page else target_page

            # ── Подтверждение оплаты ───────────────────────────────────────────
            try:
                confirmed = await _confirm_payment_in_popup(target_page)
                result["payment_confirmed"] = confirmed
            except Exception as e:
                logger.debug(f"Подтверждение оплаты: {e}")
                result["payment_confirmed"] = False

        else:
            confirmed = await _confirm_payment_in_popup(target_page)
            result["payment_confirmed"] = confirmed

        if not result["payment_confirmed"]:
            result["error"] = "Не удалось подтвердить оплату в Google Pay popup"
            return result

        if popup_page:
            try:
                await popup_page.wait_for_event("close", timeout=30000)
                logger.info("Popup Google Pay закрылся")
            except Exception:
                logger.info("Popup не закрылся автоматически")

        await page.wait_for_timeout(5000)

        # ── Ожидание успеха ────────────────────────────────────────────────────
        purchase_complete = await _wait_for_purchase_complete(page, timeout_ms=payment_timeout * 1000)
        result["payment_verified"] = purchase_complete
        result["success"] = purchase_complete or result["payment_confirmed"]

        if purchase_complete:
            logger.info("Оплата через Google Pay прошла успешно!")
        else:
            logger.warning("Страница успеха не найдена, но оплата могла пройти")
            await _screenshot(page, "payment_result_unknown")

        result["screenshot_success"] = await _take_proof_screenshot(page, "purchase_complete")

        account_result = await _check_account_and_cleanup(browser, product_name=product_name)
        result["screenshot_account"] = account_result.get("screenshot_account")
        result["cards_removed"] = account_result.get("cards_removed", 0)
        if account_result.get("purchase_verified"):
            result["success"] = True

    except Exception as e:
        logger.error(f"Ошибка Google Pay flow: {e}")
        result["error"] = str(e)
        try:
            await _screenshot(page, "google_pay_error")
        except Exception:
            pass

    finally:
        await _logout_google(browser)

    return result
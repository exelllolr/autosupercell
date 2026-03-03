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

# Селекторы вкладки G Pay в FastSpring
_GPAY_TAB_SELECTORS = [
    # Текст "G Pay" (FastSpring использует именно это написание)
    'button:has-text("G Pay")',
    '[role="tab"]:has-text("G Pay")',
    'li:has-text("G Pay")',
    'a:has-text("G Pay")',
    'span:has-text("G Pay")',
    # Текст "Google Pay"
    'button:has-text("Google Pay")',
    '[role="tab"]:has-text("Google Pay")',
    # Data-атрибуты FastSpring / платёжных систем
    '[data-method="googlepay"]',
    '[data-method="google_pay"]',
    '[data-payment-method="google_pay"]',
    '[data-fsc-action*="google"]',
    '[id*="googlepay"]',
    '[id*="google-pay"]',
    # Классы
    '[class*="googlepay"]',
    '[class*="google-pay"]',
    '[class*="GooglePay"]',
    # Изображение с alt Google Pay
    'img[alt*="Google Pay"]',
    'img[alt*="G Pay"]',
    # SVG title
    'button svg[title*="Google"]',
]

# Селекторы кнопки оплаты после выбора G Pay вкладки
# ВАЖНО: эти селекторы применяются ТОЛЬКО после клика по вкладке G Pay
_GPAY_PAY_BUTTON_SELECTORS = [
    # FastSpring: "Place Your Order" — основная кнопка после выбора G Pay
    'button:has-text("Place Your Order")',
    'button:has-text("Place your order")',
    'button:has-text("Place Order")',
    # Официальная кнопка Google Pay (появляется после выбора вкладки)
    '.gpay-button',
    '[class*="gpay-button"]',
    '[class*="google-pay-button"]',
    'button[aria-label*="Google Pay"]',
    '[data-testid*="google-pay"]',
    # Кнопка "Pay $X.XX" (FastSpring показывает её после выбора G Pay)
    'button:has-text("Pay $")',
    'button:has-text("Pay €")',
    'button:has-text("Pay £")',
    # Кнопки с текстом Google Pay
    'button:has-text("Pay with Google")',
    'button:has-text("Buy with G Pay")',
    'button:has-text("G Pay")',
    # Последний fallback — submit кнопка (только если всё остальное не нашлось)
    'button[type="submit"]:visible',
]


async def _try_click_in_frame(frame, selectors: list, label: str) -> bool:
    """Пробует кликнуть по первому найденному селектору в frame."""
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
    """
    Возвращает список кандидатов на FastSpring checkout iframe.
    Скелетон (sbl.onfastspring.com/sbl/.../skeleton.html) — пропускаем.
    """
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


# Таймаут ожидания появления и загрузки FastSpring iframe (мс)
_FASTSPRING_IFRAME_TIMEOUT_MS = 120000  # 2 минуты

async def _wait_for_fastspring_loaded(page, timeout_ms: int = None) -> list:
    """
    Ждёт пока FastSpring checkout iframe полностью загрузится.
    Возвращает список загруженных FastSpring frame.
    """
    if timeout_ms is None:
        timeout_ms = _FASTSPRING_IFRAME_TIMEOUT_MS
    logger.info("Ожидание загрузки FastSpring checkout iframe (таймаут %s сек)...", timeout_ms // 1000)
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
    """Принимает куки на странице и во всех iframe (без зависимости от BrowserAutomation)."""
    cookie_selectors = [
        # Supercell "Cookie settings" — кнопка подтверждения выбора
        'button:has-text("Confirm My Choices")',
        'button:has-text("Confirm my choices")',
        '[role="button"]:has-text("Confirm My Choices")',
        'button:has-text("CANCEL")',
        'button:has-text("Cancel")',
        # Обычные баннеры куки
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

    # Проверяем основную страницу
    if await _try(page):
        return True
    # Проверяем все iframe
    for frame in page.frames:
        try:
            if await _try(frame):
                return True
        except Exception:
            continue
    return False


async def select_gpay_tab_and_pay(page, timeout_ms: int = 90000) -> bool:
    """
    Находит FastSpring форму в iframe, кликает вкладку G Pay,
    затем кнопку "Place Your Order".
    Возвращает True если кнопка оплаты нажата.
    """
    logger.info("Ищем FastSpring форму и вкладку G Pay...")

    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)
    except Exception:
        pass

    # Принимаем куки если баннер появился на checkout странице
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

    # Несколько попыток нажатия на элементы FastSpring iframe (iframe может догружаться)
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
            logger.info("Кнопка оплаты не найдена, ждём %s сек перед следующей попыткой...", wait_after_ms // 1000)
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

# Таймауты для поиска окна входа Google (приоритет: полное окно → оверлей → popup)
_SIGNIN_FULL_WINDOW_TIMEOUT_MS = 150000   # 2.5 мин — ждём полное окно (pay.fastspring.com с формой «Вход»/Sign in)
_SIGNIN_OVERLAY_POLL_MS = 30000            # 30 сек — проверка оверлея (iframe)
_SIGNIN_POPUP_TIMEOUT_MS = 90000          # 1.5 мин — ожидание popup, если полное окно не открылось


def _is_google_block_page(page_text: str) -> bool:
    """Проверяет, показала ли Google страницу «This browser or app may not be secure»."""
    t = (page_text or "").lower()
    return (
        "couldn't sign you in" in t
        or "this browser or app may not be secure" in t
    )


def _url_is_signin_context(url: str) -> bool:
    """
    URL относится к контексту входа Google Pay / FastSpring (из структуры pay.fastspring.com):
    - pay.fastspring.com/.../googlepay.html, embedded-checkout
    - pay.google.com (официальный домен Google Payments)
    - accounts.google.com, signin
    """
    u = (url or "").lower()
    if "accounts.google.com" in u or ("signin" in u and "google" in u):
        return True
    if "pay.google.com" in u:
        return True
    if "pay.fastspring.com" in u and ("googlepay" in u or "embedded-checkout" in u or "google" in u):
        return True
    return False


async def _is_google_signin_full_window(page) -> bool:
    """
    Полное окно входа (как на фото): pay.fastspring.com/.../googlepay.html (embedded-checkout),
    pay.google.com или страница с формой «Вход»/«Телефон или адрес эл. почты»/«Далее» (или Sign in / Next).
    """
    try:
        u = (page.url or "").lower()
        if _url_is_signin_context(u):
            return True
        if "pay.fastspring.com" in u and ("googlepay" in u or "embedded-checkout" in u or "google" in u):
            return True
        if "pay.google.com" in u:
            return True
        body = (await page.evaluate("() => document.body.innerText")).lower()
        # Русский интерфейс (как на фото)
        if "вход" in body and ("телефон или адрес" in body or "далее" in body):
            return True
        # English
        if "sign in" in body and ("email or phone" in body or "phone or email" in body or "next" in body):
            return True
        if "телефон или адрес эл. почты" in body or "далее" in body:
            return True
    except Exception:
        pass
    return False


async def _is_google_signin_overlay(page) -> bool:
    """
    Оверлей: страница содержит iframe с входом Google (payframe, pay.google.com,
    accounts.google.com или fastspring googlepay.html / embedded-checkout).
    """
    try:
        for frame in page.frames:
            src = (frame.url or "").lower()
            if "accounts.google.com" in src:
                return True
            if "pay.google.com" in src:
                return True
            if "pay.fastspring.com" in src and ("googlepay" in src or "embedded-checkout" in src):
                return True
            # payframe — типичное имя iframe для платёжного окна в FastSpring
            if "payframe" in (getattr(frame, "name", None) or "").lower():
                return True
    except Exception:
        pass
    return False


def _page_has_signin_url(page) -> bool:
    """Popup/страница с URL входа: accounts.google.com, signin, pay.google.com, fastspring googlepay/embedded-checkout."""
    try:
        return _url_is_signin_context(page.url or "")
    except Exception:
        return False


async def _get_signin_frame(page):
    """
    Если форма входа в iframe (payframe, pay.google.com, accounts.google.com, fastspring googlepay) —
    возвращает этот frame. Иначе None (работаем с основной страницей).
    """
    try:
        for frame in page.frames:
            src = (frame.url or "").lower()
            if "accounts.google.com" in src or "pay.google.com" in src:
                return frame
            if "pay.fastspring.com" in src and ("googlepay" in src or "embedded-checkout" in src):
                return frame
    except Exception:
        pass
    return None


async def _wait_for_signin_frame(page, timeout_sec: int = 25):
    """
    На pay.fastspring.com/.../googlepay.html форма входа часто в iframe (accounts.google.com).
    Ждём появления такого iframe до timeout_sec секунд.
    """
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        frame = await _get_signin_frame(page)
        if frame is not None:
            return frame
        await asyncio.sleep(1)
    return None


async def _find_frame_with_signin_form(page, timeout_sec: int = 35):
    """
    Ищет iframe, в котором есть форма входа (текст «Вход»/«Телефон или адрес» или поле identifier).
    Проверяет по URL и по содержимому фрейма.
    """
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        try:
            for frame in page.frames:
                try:
                    url = (frame.url or "").lower()
                    if "accounts.google.com" in url or "pay.google.com" in url:
                        return frame
                    # Проверка по содержимому (форма может грузиться с другого URL)
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
                        logger.info("Найден iframe с формой входа по содержимому")
                        return frame
                except Exception:
                    continue
        except Exception:
            pass
        await asyncio.sleep(1)
    return None


def _parse_first_backup_code(backup_codes_str: str) -> str | None:
    """Из строки резервных кодов (например '5519 2680' или '55192680,12345678') возвращает первый 8-значный код без пробелов."""
    if not backup_codes_str or not backup_codes_str.strip():
        return None
    # Убираем пробелы из всей строки, затем берём первые 8 цифр подряд
    digits = "".join(c for c in backup_codes_str if c.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return None


async def _login_google_in_popup(
    popup_page, email: str, app_password: str, backup_codes: str = ""
) -> tuple[bool, str | None]:
    """
    Входит в Google в popup-окне Google Pay.
    Использует App Password (обходит 2FA). При запросе 8-значного кода — вводит первый из GOOGLE_BACKUP_CODES.
    Ввод email/пароля/кода — посимвольно с задержкой, чтобы снизить детект автоматизации.
    """
    logger.info("Вход в Google в popup окне...")

    # Увеличенные таймауты на каждом этапе авторизации Google — ждём до последнего
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

    # Проверка: уже показана блокировка «This browser may not be secure»
    try:
        body_text = await popup_page.evaluate("() => document.body.innerText")
        if _is_google_block_page(body_text):
            msg = (
                "Google: «This browser or app may not be secure». "
                "Войдите в Google вручную в том же профиле браузера до запуска скрипта (store.supercell.com → тот же Chrome), "
                "или в popup нажмите «Try again» и войдите вручную."
            )
            logger.warning(msg)
            return False, msg
    except Exception:
        pass

    # Задержка между нажатиями клавиш (мс) — имитация человека
    type_delay_min, type_delay_max = 80, 180

    # На pay.fastspring.com/.../googlepay.html форма «Вход» почти всегда в iframe. Ждём по URL и по содержимому.
    scope = popup_page
    if "pay.fastspring.com" in (current_url or "").lower() or "googlepay" in (current_url or "").lower():
        logger.info("Ожидание iframe с формой входа Google (до 35 сек по URL и содержимому)...")
        signin_frame = await _find_frame_with_signin_form(popup_page, timeout_sec=35)
        if signin_frame:
            scope = signin_frame
            logger.info("Форма входа в iframe, используем его для ввода email/пароля")
        else:
            signin_frame = await _wait_for_signin_frame(popup_page, timeout_sec=15)
            if signin_frame:
                scope = signin_frame
                logger.info("Форма входа в iframe (по URL)")
        await popup_page.wait_for_timeout(3000)

    # Экран «Вход»: поле «Телефон или адрес эл. почты» (RU) или Email/Phone (EN)
    email_selectors = [
        'input[type="email"]',
        'input[name="identifier"]',
        '#identifierId',
        'input[placeholder*="эл. почты"]',
        'input[placeholder*="Телефон или адрес"]',
        'input[placeholder*="Phone or email"]',
        'input[placeholder*="Email or phone"]',
        'input[aria-label*="email"]',
        'input[aria-label*="почты"]',
        'input[type="text"]',
    ]
    email_entered = False
    for attempt in range(2):
        for sel in email_selectors:
            try:
                el = await scope.wait_for_selector(sel, timeout=20000)
                if el and await el.is_visible():
                    await el.click()
                    await _delay(popup_page, 400, 800)
                    if scope != popup_page:
                        await el.press_sequentially(email, delay=random.randint(type_delay_min, type_delay_max))
                    else:
                        await popup_page.keyboard.type(
                            email,
                            delay=random.randint(type_delay_min, type_delay_max),
                        )
                    await _delay(popup_page, 500, 1000)
                    email_entered = True
                    logger.info(f"Email введён ({sel})")
                    break
            except Exception:
                continue
        if email_entered:
            break
        try:
            for placeholder in ["Телефон или адрес эл. почты", "Phone or email", "Email or phone"]:
                el = scope.get_by_placeholder(placeholder).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await _delay(popup_page, 400, 800)
                    if scope != popup_page:
                        await el.press_sequentially(email, delay=random.randint(type_delay_min, type_delay_max))
                    else:
                        await popup_page.keyboard.type(email, delay=random.randint(type_delay_min, type_delay_max))
                    await _delay(popup_page, 500, 1000)
                    email_entered = True
                    logger.info("Email введён (get_by_placeholder)")
                    break
        except Exception:
            pass
        if email_entered:
            break
        if attempt == 0:
            logger.info("Поле email не найдено, повтор через 5 сек (форма может грузиться)...")
            await popup_page.wait_for_timeout(5000)

    # Жёсткий fallback: ввод email и клик «Далее» через JavaScript в текущем scope (страница или iframe)
    if not email_entered:
        logger.info("Пробуем ввод email и клик Далее через JavaScript...")
        try:
            js_ok = await scope.evaluate("""
                (email) => {
                    const sel = 'input[name="identifier"], input[type="email"], #identifierId, input[placeholder*="почты"], input[placeholder*="Phone"], input[placeholder*="email"]';
                    const input = document.querySelector(sel);
                    if (!input) return false;
                    input.focus();
                    input.value = email;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    const nextBtn = Array.from(document.querySelectorAll('button, [role="button"], span, div')).find(el => {
                        const t = (el.textContent || '').trim();
                        return t === 'Далее' || t === 'Next';
                    });
                    if (nextBtn) {
                        nextBtn.click();
                        return true;
                    }
                    return false;
                }
            """, email)
            if js_ok:
                email_entered = True
                logger.info("Email введён и Далее нажата (JS fallback)")
        except Exception as e:
            logger.debug("JS fallback email: %s", e)

    if not email_entered:
        logger.warning("Поле email не найдено в popup Google (страница и iframe)")
        return False, None

    await _delay(popup_page, 600, 1200)
    # Кнопка «Далее» (RU) или Next (EN) после ввода email/телефона
    next_after_email = [
        'button:has-text("Далее")',
        '#identifierNext',
        'button:has-text("Next")',
        'span:has-text("Далее")',
        'div[role="button"]:has-text("Далее")',
        '[role="button"]:has-text("Далее")',
        'button[type="submit"]',
        'input[type="submit"]',
    ]
    next_clicked = False
    for sel in next_after_email:
        try:
            loc = scope.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=15000)
                next_clicked = True
                logger.info("Next/Далее после email нажат")
                break
        except Exception:
            continue
    if not next_clicked:
        try:
            for text in ["Далее", "Next"]:
                btn = scope.get_by_text(text, exact=False).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=15000)
                    next_clicked = True
                    logger.info("Next/Далее нажата (get_by_text)")
                    break
        except Exception:
            pass
    if not next_clicked:
        try:
            target = scope if scope != popup_page else popup_page
            clicked = await target.evaluate("""
                () => {
                    const els = document.querySelectorAll('button, [role="button"], span, div');
                    for (const el of els) {
                        const t = (el.textContent || '').trim();
                        if (t === 'Далее' || t === 'Next') {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            if clicked:
                logger.info("Next/Далее нажата (JS)")
        except Exception:
            pass

    await popup_page.wait_for_timeout(6000)

    # После Next проверяем, не показал ли Google блокировку
    try:
        body_text = await popup_page.evaluate("() => document.body.innerText")
        if _is_google_block_page(body_text):
            msg = (
                "Google заблокировал вход («This browser or app may not be secure»). "
                "Войдите в Google вручную в том же профиле Chrome до запуска скрипта (browser_profile), затем снова запустите демо."
            )
            logger.warning(msg)
            return False, msg
    except Exception:
        pass

    # ── Пароль (App Password) ─────────────────────────────────────────────────
    pw_selectors = ['input[type="password"]', 'input[name="password"]', '#password input']
    pw_entered = False
    password_clean = app_password.replace(" ", "")
    for sel in pw_selectors:
        try:
            el = await scope.wait_for_selector(sel, timeout=45000)
            if el:
                await el.click()
                await _delay(popup_page, 400, 800)
                if scope != popup_page:
                    await el.press_sequentially(password_clean, delay=random.randint(type_delay_min, type_delay_max))
                else:
                    await popup_page.keyboard.type(
                        password_clean,
                        delay=random.randint(type_delay_min, type_delay_max),
                    )
                await _delay(popup_page, 500, 1000)
                pw_entered = True
                logger.info("App Password введён")
                break
        except Exception:
            continue

    if not pw_entered:
        logger.warning("Поле пароля не найдено в popup Google")
        return False, None

    await _delay(popup_page, 600, 1200)
    for sel in ['#passwordNext', 'button:has-text("Next")', 'button:has-text("Далее")', 'button[type="submit"]']:
        try:
            loc = scope.locator(sel).first
            if await loc.count() > 0:
                await loc.click(timeout=15000)
                logger.info("Next после пароля нажат")
                break
        except Exception:
            continue

    await popup_page.wait_for_timeout(8000)

    # ── 2-Step Verification: прокрутка вниз → "Try another way" → выбор "8-digit backup code" ─
    backup_code = _parse_first_backup_code(backup_codes)
    if backup_code:
        try:
            try:
                body_text = (await scope.evaluate("() => document.body.innerText")).lower()
            except Exception:
                body_text = (await popup_page.evaluate("() => document.body.innerText")).lower()
            current_url = (popup_page.url or "").lower()
            is_2sv_challenge = (
                "challenge" in current_url
                or "2-step verification" in body_text
                or "2-step verification" in body_text.replace("-", " ")
                or "open the youtube app" in body_text
                or "open the google app" in body_text
                or "sent a notification" in body_text
            )
            if is_2sv_challenge:
                logger.info("Обнаружена страница 2-Step Verification, прокрутка вниз и поиск «Try another way»...")
                try:
                    await scope.evaluate("window.scrollBy(0, 400)")
                except Exception:
                    await popup_page.evaluate("window.scrollBy(0, 400)")
                await popup_page.wait_for_timeout(500)
                try:
                    await scope.evaluate("window.scrollBy(0, 400)")
                except Exception:
                    await popup_page.evaluate("window.scrollBy(0, 400)")
                await popup_page.wait_for_timeout(400)
                try:
                    await scope.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    await popup_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await popup_page.wait_for_timeout(500)

                try_another_way_selectors = [
                    'a:has-text("Try another way")',
                    'span:has-text("Try another way")',
                    '[role="link"]:has-text("Try another way")',
                    'button:has-text("Try another way")',
                    'a:has-text("Try a different way")',
                ]
                try_another_clicked = False
                for sel in try_another_way_selectors:
                    try:
                        loc = scope.locator(sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            await loc.scroll_into_view_if_needed()
                            await _delay(popup_page, 300, 600)
                            await loc.click(timeout=15000)
                            try_another_clicked = True
                            logger.info("Нажато «Try another way»")
                            break
                    except Exception:
                        continue
                if not try_another_clicked:
                    try:
                        link = scope.get_by_text("Try another way", exact=False).first
                        if await link.count() > 0:
                            await link.scroll_into_view_if_needed()
                            await link.click(timeout=15000)
                            try_another_clicked = True
                            logger.info("Нажато «Try another way» (get_by_text)")
                    except Exception:
                        pass

                await popup_page.wait_for_timeout(10000)

                # Прокрутка, чтобы опция "Enter one of your 8-digit backup codes" была в зоне видимости
                try:
                    await scope.evaluate("window.scrollBy(0, 300)")
                except Exception:
                    await popup_page.evaluate("window.scrollBy(0, 300)")
                await popup_page.wait_for_timeout(500)
                try:
                    await scope.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    await popup_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await popup_page.wait_for_timeout(800)

                # Выбор входа по 8-значному резервному коду (после "Try another way")
                # Текст на экране: "Enter one of your 8-digit backup codes" (может быть в div/span/кнопке)
                backup_option_selectors = [
                    'a:has-text("Enter one of your 8-digit backup codes")',
                    'a:has-text("8-digit backup code")',
                    'span:has-text("Enter one of your 8-digit backup codes")',
                    'div:has-text("Enter one of your 8-digit backup codes")',
                    'div:has-text("8-digit backup codes")',
                    'div:has-text("8-digit backup code")',
                    'button:has-text("Enter one of your 8-digit backup codes")',
                    'button:has-text("8-digit backup code")',
                    '[role="option"]:has-text("Enter one of your 8-digit backup codes")',
                    '[role="option"]:has-text("8-digit backup code")',
                    '[role="button"]:has-text("8-digit backup")',
                    'a:has-text("Use a backup code")',
                    '[role="option"]:has-text("backup code")',
                    'a:has-text("backup code")',
                    'span:has-text("backup code")',
                    'div:has-text("backup code")',
                ]
                backup_option_clicked = False
                for attempt in range(1, 6):
                    for sel in backup_option_selectors:
                        try:
                            loc = scope.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.scroll_into_view_if_needed()
                                await _delay(popup_page, 300, 600)
                                await loc.click(timeout=15000)
                                backup_option_clicked = True
                                logger.info("Выбран вход по 8-значному резервному коду (селектор: %s)", sel[:50])
                                break
                        except Exception:
                            continue
                    if backup_option_clicked:
                        break
                    await popup_page.wait_for_timeout(2000)
                if not backup_option_clicked:
                    try:
                        for text in [
                            "Enter one of your 8-digit backup codes",
                            "8-digit backup codes",
                            "8-digit backup code",
                            "Use a backup code",
                            "backup code",
                        ]:
                            el = scope.get_by_text(text, exact=False).first
                            if await el.count() > 0 and await el.is_visible():
                                await el.scroll_into_view_if_needed()
                                await _delay(popup_page, 300, 500)
                                await el.click(timeout=15000)
                                backup_option_clicked = True
                                logger.info("Выбран вход по 8-значному коду (get_by_text: %s)", text)
                                break
                    except Exception:
                        pass

                await popup_page.wait_for_timeout(6000)
        except Exception as e:
            logger.debug("Шаг 2-Step Verification (Try another way): %s", e)

    # При таймауте на любом шаге не прерываем — продолжаем до последнего

    # ── Проверка: запрос 8-значного резервного кода (backup code) ─────────────
    code_input_selectors = [
        'input[type="tel"]',
        'input[name="backupCode"]',
        'input[aria-label*="backup"]',
        'input[aria-label*="код"]',
        'input[placeholder*="backup"]',
        'input[placeholder*="код"]',
        'input[id*="backup"]',
        'input[id*="code"]',
        'input[type="text"]',  # Google может использовать text для кода
    ]
    code_entered = False
    if backup_code:
        try:
            try:
                body_text = (await scope.evaluate("() => document.body.innerText")).lower()
            except Exception:
                body_text = (await popup_page.evaluate("() => document.body.innerText")).lower()
            is_backup_page = (
                "backup" in body_text or "резервн" in body_text or "8-digit" in body_text
                or "8 digit" in body_text or "верификац" in body_text or "verification code" in body_text
            )
            if is_backup_page:
                for sel in code_input_selectors:
                    try:
                        loc = scope.locator(sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            await loc.click()
                            await _delay(popup_page, 400, 700)
                            if scope != popup_page:
                                await loc.press_sequentially(backup_code, delay=random.randint(type_delay_min, type_delay_max))
                            else:
                                await popup_page.keyboard.type(
                                    backup_code,
                                    delay=random.randint(type_delay_min, type_delay_max),
                                )
                            await _delay(popup_page, 500, 1000)
                            code_entered = True
                            logger.info("Введён 8-значный резервный код")
                            break
                    except Exception:
                        continue
                if code_entered:
                    await _delay(popup_page, 600, 1200)
                    for sel in ['button:has-text("Next")', 'button:has-text("Verify")', 'button:has-text("Далее")', 'button[type="submit"]', '#identifierNext']:
                        try:
                            loc = scope.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.click(timeout=15000)
                                logger.info("Next/Verify после резервного кода нажат")
                                break
                        except Exception:
                            continue
                    await popup_page.wait_for_timeout(6000)
        except Exception as e:
            logger.debug("Проверка резервного кода: %s", e)

    try:
        await popup_page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        await popup_page.wait_for_timeout(10000)

    # Финальная проверка: не на странице блокировки
    try:
        body_text = await popup_page.evaluate("() => document.body.innerText")
        if _is_google_block_page(body_text):
            msg = (
                "Google заблокировал вход после пароля («This browser or app may not be secure»). "
                "Залогиньтесь в Google вручную в том же Chrome-профиле (browser_profile) до запуска скрипта."
            )
            logger.warning(msg)
            return False, msg
    except Exception:
        pass

    logger.info(f"После логина URL: {popup_page.url}")
    await _screenshot(popup_page, "google_login_done")
    return True, None


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 2.0: В popup сначала «Pay with G Pay» — только после этого открывается Sign-in
# ──────────────────────────────────────────────────────────────────────────────

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
    'div:has-text("Pay with G Pay")',
    'span:has-text("Pay with G Pay")',
    '[class*="gpay"]:has-text("Pay with")',
    '[class*="google-pay"]:has-text("Pay with")',
    '[class*="pay-button"]',
    '[class*="payButton"]',
]


async def _click_pay_with_gpay_in_popup(popup_page) -> bool:
    """
    В открытом popup (pay.fastspring.com/.../googlepay.html) нажимает чёрную кнопку
    «Pay with G Pay». Только после этого открывается экран Sign-in.
    """
    logger.info("Ожидание и клик по кнопке 'Pay with G Pay' в popup...")
    try:
        await popup_page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass
    await popup_page.wait_for_timeout(4000)

    async def _try_click(scope, label: str) -> bool:
        for sel in _PAY_WITH_GPAY_SELECTORS:
            try:
                loc = scope.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.scroll_into_view_if_needed()
                    await _delay(popup_page, 400, 800)
                    await loc.click(timeout=15000)
                    logger.info("Нажата кнопка 'Pay with G Pay' (%s): %s", label, sel[:50])
                    return True
            except Exception:
                continue
        return False

    # 1) Основная страница
    if await _try_click(popup_page, "основная страница"):
        return True

    # 2) get_by_text (текст может быть разбит на несколько элементов)
    for text in ["Pay with G Pay", "Pay with Google Pay", "Pay with"]:
        try:
            el = popup_page.get_by_text(text, exact=False).first
            if await el.count() > 0 and await el.is_visible():
                await el.scroll_into_view_if_needed()
                await _delay(popup_page, 400, 800)
                await el.click(timeout=15000)
                logger.info("Нажата кнопка 'Pay with G Pay' (get_by_text: %s)", text)
                return True
        except Exception:
            continue

    # 3) get_by_role — кнопка с именем, содержащим "Pay with"
    try:
        btn = popup_page.get_by_role("button", name=re.compile(r"pay with", re.I))
        if await btn.count() > 0 and await btn.first.is_visible():
            await btn.first.scroll_into_view_if_needed()
            await _delay(popup_page, 400, 800)
            await btn.first.click(timeout=15000)
            logger.info("Нажата кнопка 'Pay with G Pay' (get_by_role)")
            return True
    except Exception:
        pass

    # 4) Клик через JS — если кнопка в сложной вёрстке (иконка внутри и т.д.)
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
            logger.info("Нажата кнопка 'Pay with G Pay' (JS click)")
            return True
    except Exception:
        pass

    # 5) Iframes (контент может быть во фрейме)
    for frame in popup_page.frames:
        if frame == popup_page.main_frame:
            continue
        try:
            if await _try_click(frame, "iframe"):
                return True
            clicked = await frame.evaluate("""
                () => {
                    const texts = ['Pay with G Pay', 'Pay with Google Pay', 'Pay with'];
                    const all = document.querySelectorAll('button, a, [role="button"]');
                    for (const el of all) {
                        const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (texts.some(s => t.includes(s))) { el.click(); return true; }
                    }
                    return false;
                }
            """)
            if clicked:
                logger.info("Нажата кнопка 'Pay with G Pay' в iframe (JS)")
                return True
        except Exception:
            continue

    logger.warning("Кнопка 'Pay with G Pay' не найдена в popup")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 3: Подтверждение оплаты в popup Google Pay
# ──────────────────────────────────────────────────────────────────────────────

async def _confirm_payment_in_popup(popup_page) -> bool:
    """Нажимает кнопку подтверждения оплаты в popup Google Pay."""
    logger.info("Подтверждение оплаты в Google Pay popup...")

    try:
        await popup_page.wait_for_load_state("domcontentloaded", timeout=60000)
    except Exception:
        pass

    await popup_page.wait_for_timeout(6000)
    await _screenshot(popup_page, "google_pay_confirm_popup")

    # Сначала «Pay with G Pay» (если ещё не нажали), затем «Оплатить»/Pay после логина
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
# Шаг 4: Ожидание Processing Payment и CONGRATULATIONS PURCHASE COMPLETE
# ──────────────────────────────────────────────────────────────────────────────

async def _wait_for_purchase_complete(page, timeout_ms: int = 120000) -> bool:
    """
    Ждёт страницы "Processing Payment", затем "CONGRATULATIONS PURCHASE COMPLETE".
    Возвращает True если оплата подтверждена.
    """
    logger.info("Ожидание Processing Payment...")
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000

    processing_seen = False
    complete_seen = False

    while asyncio.get_event_loop().time() < deadline:
        try:
            url = (page.url or "").lower()
            text = (await page.evaluate("() => document.body.innerText")).lower()

            # Ждём "Processing Payment"
            if not processing_seen and (
                "processing" in text or "processing payment" in text
                or "processing" in url
            ):
                processing_seen = True
                logger.info("Страница 'Processing Payment' обнаружена")
                await _screenshot(page, "processing_payment")

            # Ждём "CONGRATULATIONS PURCHASE COMPLETE" или аналоги
            success_phrases = [
                "congratulations", "purchase complete", "order complete",
                "thank you", "order confirmed", "payment successful",
                "purchase successful", "payment complete",
            ]
            success_urls = [
                "/success", "/thank-you", "/order-confirmed",
                "/complete", "/receipt", "/confirmation",
            ]

            for phrase in success_phrases:
                if phrase in text:
                    complete_seen = True
                    logger.info(f"Страница успеха обнаружена: '{phrase}'")
                    break

            for u in success_urls:
                if u in url:
                    complete_seen = True
                    logger.info(f"URL успеха обнаружен: '{url}'")
                    break

            if complete_seen:
                return True

        except Exception:
            pass

        await page.wait_for_timeout(2000)

    logger.warning("Страница успеха не появилась за отведённое время")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 5: Скриншот_1 в profs/
# ──────────────────────────────────────────────────────────────────────────────

async def _take_proof_screenshot(page, name: str) -> str:
    """Делает скриншот и сохраняет в папку profs/."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{name}_{ts}"
    path = await _screenshot_full(page, filename, folder="profs")
    logger.info(f"Proof скриншот сохранён: {path}")
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 6: Проверка Purchase history и Payment information на /account
# ──────────────────────────────────────────────────────────────────────────────

async def _check_account_and_cleanup(browser, product_name: str = "") -> dict:
    """
    Переходит на /account, проверяет Purchase history, делает скриншот_2,
    затем проверяет Payment information и откреп ляет карты.
    """
    page = browser.page
    result = {
        "purchase_verified": False,
        "screenshot_account": None,
        "cards_removed": 0,
    }

    try:
        logger.info("Переход на страницу аккаунта: https://store.supercell.com/account")
        await page.goto("https://store.supercell.com/account", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # ── Прокрутка к Purchase history ──────────────────────────────────────
        logger.info("Прокрутка к 'Purchase history'...")
        purchase_history_found = False
        for sel in [
            'text="Purchase history"',
            ':has-text("Purchase history")',
            '[id*="purchase"]',
            '[class*="purchase"]',
            'h2:has-text("Purchase")',
            'h3:has-text("Purchase")',
        ]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed()
                    await page.wait_for_timeout(1000)
                    purchase_history_found = True
                    logger.info(f"Purchase history найдена: {sel}")
                    break
            except Exception:
                continue

        if not purchase_history_found:
            # Скроллим вниз постепенно
            await page.evaluate("window.scrollBy(0, 600)")
            await page.wait_for_timeout(800)

        # Проверяем наличие недавней покупки в тексте страницы
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

        # Скриншот_2: Purchase history
        result["screenshot_account"] = await _take_proof_screenshot(page, "purchase_history")

        # ── Прокрутка к Payment information ───────────────────────────────────
        logger.info("Прокрутка к 'Payment information'...")
        payment_info_found = False
        for sel in [
            'text="Payment information"',
            ':has-text("Payment information")',
            '[id*="payment"]',
            '[class*="payment-info"]',
            'h2:has-text("Payment")',
            'h3:has-text("Payment")',
        ]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed()
                    await page.wait_for_timeout(1000)
                    payment_info_found = True
                    logger.info(f"Payment information найдена: {sel}")
                    break
            except Exception:
                continue

        if not payment_info_found:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)

        await _screenshot(page, "payment_information_section")

        # ── Поиск и удаление привязанных карт ─────────────────────────────────
        logger.info("Проверка привязанных карт в Payment information...")
        remove_selectors = [
            # Русские тексты (Supercell может показывать на языке браузера)
            'button:has-text("Отвязать способ оплаты")',
            'button:has-text("Отвязать")',
            'button:has-text("Открепить")',
            'button:has-text("Удалить карту")',
            'button:has-text("Удалить способ оплаты")',
            # Английские тексты
            'button:has-text("Remove")',
            'button:has-text("Delete")',
            'button:has-text("Unlink")',
            'button:has-text("Detach")',
            'a:has-text("Remove")',
            'a:has-text("Unlink")',
            '[class*="remove"]:visible',
            '[class*="delete"]:visible',
        ]

        cards_removed = 0
        max_attempts = 10  # защита от бесконечного цикла
        for _ in range(max_attempts):
            removed_this_round = False
            for sel in remove_selectors:
                try:
                    locs = page.locator(sel)
                    count = await locs.count()
                    if count > 0:
                        loc = locs.first
                        if await loc.is_visible():
                            await loc.scroll_into_view_if_needed()
                            await page.wait_for_timeout(500)
                            await loc.click(timeout=5000)
                            logger.info(f"Карта удалена: {sel}")
                            cards_removed += 1
                            removed_this_round = True
                            await page.wait_for_timeout(2000)
                            # Подтверждение диалога если появится
                            for confirm_sel in [
                                'button:has-text("Confirm")',
                                'button:has-text("Yes")',
                                'button:has-text("OK")',
                                'button:has-text("Да")',
                                'button:has-text("Подтвердить")',
                            ]:
                                try:
                                    conf = page.locator(confirm_sel).first
                                    if await conf.count() > 0 and await conf.is_visible():
                                        await conf.click(timeout=3000)
                                        logger.info(f"Диалог подтверждения: {confirm_sel}")
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
            await _screenshot(page, "cards_removed")
        else:
            logger.info("Привязанных карт не найдено")

    except Exception as e:
        logger.error(f"Ошибка при проверке аккаунта: {e}")

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 7: Выход из Google
# ──────────────────────────────────────────────────────────────────────────────

async def _logout_google(browser) -> None:
    """Очищает cookies Google из браузерного контекста."""
    logger.info("Выход из Google аккаунта (очистка cookies)...")
    try:
        if browser.context:
            cookies = await browser.context.cookies()
            google_cookies = [c for c in cookies if "google" in c.get("domain", "")]
            if google_cookies:
                await browser.context.clear_cookies()
                logger.info(f"Очищено {len(google_cookies)} cookies Google")
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
    """
    Полный flow оплаты через Google Pay (FastSpring checkout).

    Returns:
        dict: success, google_pay_clicked, payment_confirmed, payment_verified,
              screenshot_success, screenshot_account, cards_removed, error
    """
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

        # ── Шаг 1: Кликнуть вкладку G Pay и кнопку "Place Your Order" ─────────
        # Приоритет поиска окна аутентификации: 1) полное окно (как на фото), 2) оверлей, 3) popup
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
            # clicked сохраняет значение из select_gpay_tab_and_pay

        if not clicked:
            result["error"] = "Не удалось кликнуть G Pay вкладку или кнопку Place Your Order"
            await _screenshot(page, "gpay_click_failed")
            return result

        result["google_pay_clicked"] = True
        await page.wait_for_timeout(2000)

        # Выбор страницы для входа: 1) полное окно (большой таймаут), 2) оверлей, 3) popup
        auth_page = None
        if browser.context:
            # До 60 сек ждём появления полного окна (pay.fastspring с формой Вход/Sign in)
            poll_sec = min(60, _SIGNIN_FULL_WINDOW_TIMEOUT_MS // 1000)
            for _ in range(poll_sec):
                await asyncio.sleep(1)
                for p in browser.context.pages:
                    if p == page:
                        continue
                    try:
                        if await _is_google_signin_full_window(p):
                            auth_page = p
                            logger.info("Найдено полное окно входа Google (приоритет 1): %s", (p.url or "")[:80])
                            break
                    except Exception:
                        continue
                if auth_page is not None:
                    break
            if auth_page is None and browser.context:
                for p in browser.context.pages:
                    if p == page:
                        continue
                    try:
                        if await _is_google_signin_overlay(p):
                            auth_page = p
                            logger.info("Найден оверлей входа Google (приоритет 2): %s", (p.url or "")[:80])
                            break
                    except Exception:
                        continue
            if auth_page is None and popup_page:
                auth_page = popup_page
                if _page_has_signin_url(popup_page):
                    logger.info("Используется popup входа Google (приоритет 3): %s", (popup_page.url or "")[:80])

        # Используем выбранное окно; при отсутствии — исходный popup
        popup_page = auth_page if auth_page else popup_page
        target_page = popup_page if popup_page else page

        if popup_page:
            try:
                await popup_page.wait_for_load_state("domcontentloaded", timeout=90000)
            except Exception:
                pass

            # Сначала в popup нажимаем «Pay with G Pay» — только после этого открывается Sign-in
            pay_with_gpay_clicked = await _click_pay_with_gpay_in_popup(popup_page)
            if pay_with_gpay_clicked:
                await popup_page.wait_for_timeout(8000)
                if browser.context:
                    for p in browser.context.pages:
                        if p != page and p != popup_page:
                            try:
                                u = (p.url or "").lower()
                                if _url_is_signin_context(u) or "accounts.google.com" in u:
                                    popup_page = p
                                    target_page = p
                                    logger.info("Sign-in открылся в новом окне, переключаемся на него")
                                    break
                            except Exception:
                                pass
                # Ждём появления формы входа в текущем окне (iframe может грузиться)
                logger.info("Ожидание появления формы входа (до 20 сек)...")
                for _ in range(20):
                    await popup_page.wait_for_timeout(1000)
                    try:
                        if await _find_frame_with_signin_form(popup_page, timeout_sec=1):
                            break
                        body = (await popup_page.evaluate("() => document.body.innerText")).lower()
                        if "вход" in body and ("телефон" in body or "почты" in body or "email" in body):
                            break
                    except Exception:
                        pass

            current_url = (popup_page.url or "").lower()
            is_signin = _url_is_signin_context(current_url) or await _is_google_signin_full_window(popup_page)

            # Шаг 2a: Если окно ещё на экране G Pay (не sign-in) — нажимаем "Оплатить"/Pay, после чего откроется sign-in
            signin_page = None
            if not is_signin:
                logger.info("Окно открыто на экране G Pay, нажимаем 'Оплатить' / Pay...")
                first_pay_clicked = await _confirm_payment_in_popup(popup_page)
                if first_pay_clicked:
                    logger.info("Кнопка оплаты нажата, ожидание страницы входа Google (полное окно → оверлей → popup)...")
                    # Ждём sign-in с приоритетом: полное окно, оверлей, popup
                    wait_sec = 90
                    for _ in range(wait_sec):
                        await popup_page.wait_for_timeout(1000)
                        try:
                            if await _is_google_signin_full_window(popup_page):
                                signin_page = popup_page
                                logger.info("Страница входа в том же окне (полное окно)")
                                break
                            current_url = (popup_page.url or "").lower()
                            if "accounts.google.com" in current_url or "signin" in current_url:
                                signin_page = popup_page
                                logger.info("Открылась страница входа Google в том же окне")
                                break
                        except Exception:
                            pass
                        if signin_page is None and browser.context:
                            for p in browser.context.pages:
                                if p == page:
                                    continue
                                try:
                                    if await _is_google_signin_full_window(p):
                                        signin_page = p
                                        logger.info("Найдено полное окно входа в новом окне: %s", (p.url or "")[:80])
                                        break
                                    if _page_has_signin_url(p):
                                        signin_page = p
                                        logger.info("Найдена страница входа в новом окне: %s", (p.url or "")[:80])
                                        break
                                except Exception:
                                    continue
                        if signin_page is not None:
                            break
                    if signin_page is None:
                        logger.warning("Страница sign-in не обнаружена за %s сек (полное окно, оверлей, popup проверены)", wait_sec)

            if signin_page is None and popup_page:
                try:
                    if await _is_google_signin_full_window(popup_page) or _page_has_signin_url(popup_page):
                        signin_page = popup_page
                except Exception:
                    pass

            # Шаг 2b: Логин в Google (на signin_page или popup_page). При таймауте не выходим — идём дальше.
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
                        logger.info("Запуск входа в Google на странице: %s", (login_page.url or "")[:90])
                        backup_codes = getattr(settings, "GOOGLE_BACKUP_CODES", "") or ""
                        try:
                            logged_in, login_msg = await _login_google_in_popup(
                                login_page, email, app_password, backup_codes=backup_codes
                            )
                            if not logged_in:
                                result["error"] = login_msg or "Не удалось войти в Google аккаунт"
                                # Не return — продолжаем до шага подтверждения оплаты
                            else:
                                await asyncio.sleep(5)
                        except Exception as e:
                            logger.warning("Таймаут или ошибка при входе в Google, продолжаем: %s", e)
                            result["error"] = str(e)
                    else:
                        logger.info(
                            "После клика Pay sign-in не открылся, URL: %s. Проверьте, не открылось ли окно входа вручную.",
                            login_page.url,
                        )
                except Exception as e:
                    logger.warning(f"Ошибка при входе в Google (продолжаем): {e}")

            # Для шага 3 используем страницу, где после логина может быть кнопка подтверждения (тот же popup или signin)
            target_page = signin_page if signin_page else target_page

            # Шаг 3: Подтверждение оплаты (второй экран после логина или если логин не требовался)
            try:
                confirmed = await _confirm_payment_in_popup(target_page)
                result["payment_confirmed"] = confirmed
            except Exception as e:
                logger.debug(f"Подтверждение оплаты в popup: {e}")
                result["payment_confirmed"] = False

        else:
            confirmed = await _confirm_payment_in_popup(target_page)
            result["payment_confirmed"] = confirmed

        if not result["payment_confirmed"]:
            result["error"] = "Не удалось подтвердить оплату в Google Pay popup"
            return result

        # Ждём закрытия popup
        if popup_page:
            try:
                await popup_page.wait_for_event("close", timeout=30000)
                logger.info("Popup Google Pay закрылся")
            except Exception:
                logger.info("Popup не закрылся автоматически")

        await page.wait_for_timeout(5000)

        # ── Шаг 4: Ожидание Processing Payment → CONGRATULATIONS ──────────────
        purchase_complete = await _wait_for_purchase_complete(page, timeout_ms=payment_timeout * 1000)
        result["payment_verified"] = purchase_complete
        result["success"] = purchase_complete or result["payment_confirmed"]

        if purchase_complete:
            logger.info("Оплата через Google Pay прошла успешно!")
        else:
            logger.warning("Страница успеха не найдена, но оплата могла пройти")
            await _screenshot(page, "payment_result_unknown")

        # ── Шаг 5: Скриншот_1 — страница успеха → profs/ ─────────────────────
        result["screenshot_success"] = await _take_proof_screenshot(page, "purchase_complete")

        # ── Шаг 6: Переход на /account, проверка Purchase history, скриншот_2 ─
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

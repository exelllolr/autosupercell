"""
Модуль оплаты через Google Pay на Supercell Store (FastSpring или Appcharge checkout).

Flow FastSpring:
1. После Checkout открывается страница FastSpring с формой оплаты
2. Форма содержит вкладки: [Card] [PayPal] [G Pay] [Amazon Pay]
3. Кликаем вкладку "G Pay" → "Place Your Order" → popup Google Pay
4. В popup: логин Google (email + App Password), подтверждение оплаты
5. Ждём "Processing Payment" → "CONGRATULATIONS PURCHASE COMPLETE"
6. Скриншот_1 в profs/, переход на /account, проверка Purchase history, скриншот_2, отвязка карт, выход из Google

Flow Appcharge (параллельно с FastSpring):
- Обнаруживается сразу (powered by appcharge / "buy with g pay") ИЛИ если FastSpring не открылся
- Каждые 5 сек во время ожидания FastSpring проверяем наличие Appcharge
- Выбираем плашку Google Pay, ждём прогрузки формы, нажимаем "Place Your Order"
- Откроется окно Sign in → вводим данные, оплачиваем
- Дальше заходим в аккаунт, проверяем покупку и выходим из аккаунта как обычно

Claude AI помощь:
- Если стандартные CSS-селекторы не нашли вкладку G Pay — делаем скриншот и спрашиваем Claude
- Если стандартные селекторы не нашли кнопку Place Your Order — делаем скриншот и спрашиваем Claude
- Требуется ANTHROPIC_API_KEY в .env (AI_PROVIDER=claude)
"""

import asyncio
import base64
import os
import random
from datetime import datetime
from loguru import logger

from app.config import settings


# ──────────────────────────────────────────────────────────────────────────────
# Claude AI helper: определение вкладки Google Pay и помощь в оплате
# ──────────────────────────────────────────────────────────────────────────────

async def _claude_find_gpay_selector(page, context_hint: str = "") -> str | None:
    """
    Делает скриншот страницы и спрашивает Claude API, какой CSS-селектор
    нажать для перехода к Google Pay. Возвращает найденный селектор или None.
    """
    anthropic_key = getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    model = getattr(settings, "CLAUDE_MODEL", "claude-3-5-sonnet-20241022") or "claude-3-5-sonnet-20241022"
    if not anthropic_key:
        logger.debug("ANTHROPIC_API_KEY не задан, пропускаем Claude AI поиск G Pay")
        return None

    try:
        import aiohttp

        # Скриншот текущего состояния страницы
        _ensure_dir("screenshots")
        screenshot_path = "screenshots/claude_gpay_analysis.png"
        await page.screenshot(path=screenshot_path, full_page=False)

        with open(screenshot_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        # Также получаем HTML для анализа
        try:
            html_snippet = await page.evaluate("""() => {
                const body = document.body;
                const clone = body.cloneNode(true);
                // Убираем скрипты и стили для краткости
                clone.querySelectorAll('script,style,noscript').forEach(e => e.remove());
                return clone.innerHTML.slice(0, 8000);
            }""")
        except Exception:
            html_snippet = ""

        prompt = f"""You are analyzing a payment checkout page screenshot.
{context_hint}

Your task: Find the Google Pay tab/option/button on this page.

Look for:
- A tab labeled "G Pay", "Google Pay", or showing the Google Pay logo
- A payment method selector or radio button for Google Pay
- Any button or element to select Google Pay as payment method

Based on the screenshot and the HTML snippet below, return ONLY a valid CSS selector string that I can use to click the Google Pay tab/option. 
Return just the selector, nothing else. If you cannot find it, return: NOT_FOUND

HTML snippet:
{html_snippet[:4000]}
"""

        payload = {
            "model": model,
            "max_tokens": 256,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

        selector = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                selector = block["text"].strip()
                break

        if not selector or selector == "NOT_FOUND" or len(selector) > 300:
            logger.debug(f"Claude AI: G Pay селектор не найден (ответ: {selector[:80]})")
            return None

        logger.info(f"Claude AI предложил селектор G Pay: {selector}")
        return selector

    except Exception as e:
        logger.debug(f"Claude AI поиск G Pay: ошибка {e}")
        return None


async def _claude_find_pay_button_selector(page, context_hint: str = "") -> str | None:
    """
    Делает скриншот после выбора Google Pay и спрашивает Claude,
    какой селектор нажать для подтверждения оплаты ("Place Your Order" и т.п.).
    """
    anthropic_key = getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    model = getattr(settings, "CLAUDE_MODEL", "claude-3-5-sonnet-20241022") or "claude-3-5-sonnet-20241022"
    if not anthropic_key:
        return None

    try:
        import aiohttp

        _ensure_dir("screenshots")
        screenshot_path = "screenshots/claude_pay_button_analysis.png"
        await page.screenshot(path=screenshot_path, full_page=False)

        with open(screenshot_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        try:
            html_snippet = await page.evaluate("""() => {
                const body = document.body;
                const clone = body.cloneNode(true);
                clone.querySelectorAll('script,style,noscript').forEach(e => e.remove());
                return clone.innerHTML.slice(0, 8000);
            }""")
        except Exception:
            html_snippet = ""

        prompt = f"""You are analyzing a Google Pay checkout page screenshot.
{context_hint}

Google Pay has been selected as payment method. Now find the button to CONFIRM/SUBMIT the payment.

Look for:
- "Place Your Order" button
- "Pay" button with a price (e.g. "Pay $0.99")
- "Buy with G Pay" button
- "Place Order" button
- Any primary action button to complete the payment

Based on the screenshot and HTML snippet, return ONLY a valid CSS selector to click that button.
Return just the selector, nothing else. If not found, return: NOT_FOUND

HTML snippet:
{html_snippet[:4000]}
"""

        payload = {
            "model": model,
            "max_tokens": 256,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

        selector = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                selector = block["text"].strip()
                break

        if not selector or selector == "NOT_FOUND" or len(selector) > 300:
            logger.debug(f"Claude AI: кнопка оплаты не найдена (ответ: {selector[:80]})")
            return None

        logger.info(f"Claude AI предложил селектор кнопки оплаты: {selector}")
        return selector

    except Exception as e:
        logger.debug(f"Claude AI поиск кнопки оплаты: ошибка {e}")
        return None


async def _try_click_claude_selector(frame_or_page, selector: str, label: str) -> bool:
    """Пробует кликнуть по селектору, предложенному Claude AI."""
    if not selector:
        return False
    try:
        loc = frame_or_page.locator(selector).first
        count = await loc.count()
        if count > 0:
            visible = await loc.is_visible()
            if visible:
                await loc.scroll_into_view_if_needed()
                await loc.click(timeout=8000)
                logger.info(f"{label} [Claude AI]: {selector}")
                return True
    except Exception as e:
        logger.debug(f"Claude AI клик не удался ({selector}): {e}")
    return False


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

# Селекторы вкладки G Pay / Google Pay в FastSpring и Appcharge.
# ПОРЯДОК ВАЖЕН: сначала самые точные (специфичные для FastSpring), потом общие.
# НЕ используем 'div:has-text("Google Pay")' — слишком широкий, матчит весь body.
_GPAY_TAB_SELECTORS = [
    # ── FastSpring: вкладка выглядит как кнопка/div с текстом "Google Pay" внутри платёжного переключателя ──
    # Точные селекторы для структуры FastSpring (store.supercell.com)
    '[data-fsc-item-path-value*="google"]',
    '[data-fsc-action*="google"]',
    '[data-method="googlepay"]',
    '[data-method="google_pay"]',
    '[data-payment-method="google_pay"]',
    '[id*="googlepay"]',
    '[id*="google-pay"]',
    '[id*="google_pay"]',
    # Классы специфичные для Google Pay
    '[class*="googlepay"]:not(body):not(html)',
    '[class*="google-pay"]:not(body):not(html)',
    '[class*="GooglePay"]:not(body):not(html)',
    '[class*="gpay"]:not(body):not(html)',
    # Кнопки с точным текстом
    'button:has-text("Google Pay")',
    'button:has-text("G Pay")',
    # Роли вкладок/опций (radio-группа платёжных методов)
    '[role="tab"]:has-text("Google Pay")',
    '[role="tab"]:has-text("G Pay")',
    '[role="radio"]:has-text("Google Pay")',
    '[role="option"]:has-text("Google Pay")',
    # li/a элементы меню выбора метода
    'li:has-text("Google Pay")',
    'li:has-text("G Pay")',
    'a:has-text("Google Pay")',
    'a:has-text("G Pay")',
    # label (radio input + label — типичная структура FastSpring)
    'label:has-text("Google Pay")',
    'label:has-text("G Pay")',
    # Изображение с alt Google Pay (иконка в вкладке)
    'img[alt*="Google Pay"]',
    'img[alt*="G Pay"]',
    'img[src*="google-pay"]',
    'img[src*="googlepay"]',
    # SVG title
    'button svg[title*="Google"]',
    # span ТОЛЬКО внутри кнопок/лейблов (не весь body)
    'button span:has-text("Google Pay")',
    'label span:has-text("Google Pay")',
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
    """
    Пробует кликнуть по первому найденному селектору в frame.
    Пропускает элементы-контейнеры (body, html, крупные div на всю страницу).
    """
    for sel in selectors:
        try:
            locs = frame.locator(sel)
            count = await locs.count()
            if count == 0:
                continue
            # Если несколько — перебираем, берём первый видимый и не-контейнер
            for i in range(min(count, 5)):
                loc = locs.nth(i)
                try:
                    visible = await loc.is_visible()
                    if not visible:
                        continue
                    # Проверяем что это не огромный контейнер (body/wrapper)
                    tag = await loc.evaluate("el => el.tagName.toLowerCase()")
                    if tag in ("body", "html"):
                        continue
                    box = await loc.bounding_box()
                    if box and box["width"] > 800 and box["height"] > 400:
                        # Слишком большой элемент — это контейнер, пропускаем
                        logger.debug(f"Пропуск контейнера {tag} ({box['width']}x{box['height']}): {sel}")
                        continue
                    await loc.scroll_into_view_if_needed()
                    await loc.click(timeout=5000)
                    logger.info(f"{label}: {sel}")
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def _is_fastspring_url(url: str) -> bool:
    """Возвращает True если URL относится к FastSpring checkout."""
    url = (url or "").lower()
    return (
        "onfastspring.com/embedded-checkout" in url
        or "onfastspring.com" in url
        or "cloudfront.net/supercell/embedded-checkout" in url
        or "fastspring.com" in url
    )


def _is_fastspring_checkout_page(page) -> bool:
    """
    Проверяет, что ТЕКУЩАЯ страница (не iframe) является FastSpring checkout.
    Это происходит когда FastSpring открывается как отдельная страница/popup,
    а не как embedded iframe.
    """
    try:
        url = (page.url or "").lower()
        # store.supercell.com/... с FastSpring формой на странице
        if _is_fastspring_url(url):
            return True
        # Основная страница store.supercell.com — FastSpring рендерит форму прямо на ней
        if "store.supercell.com" in url:
            return True
    except Exception:
        pass
    return False


def _get_fastspring_frames(page):
    """
    Возвращает список кандидатов на FastSpring checkout.
    ВАЖНО: На скриншоте FastSpring рендерит форму прямо на странице store.supercell.com
    (не в iframe). Поэтому сначала проверяем основную страницу, потом iframe.
    Скелетон (sbl.onfastspring.com/sbl/.../skeleton.html) — пропускаем.
    """
    candidates = []
    try:
        # Проверяем основную страницу — FastSpring может рендериться прямо на ней
        # (store.supercell.com с формой [Card][PayPal][Google Pay][Amazon Pay])
        if _is_fastspring_checkout_page(page):
            candidates.append(page.main_frame)

        for frame in page.frames:
            if frame == page.main_frame:
                continue
            url = frame.url or ""
            if "skeleton.html" in url or "sbl.onfastspring.com/sbl/" in url:
                continue
            if _is_fastspring_url(url):
                candidates.append(frame)
    except Exception:
        pass
    return candidates


# Таймаут ожидания появления и загрузки FastSpring iframe (мс)
_FASTSPRING_IFRAME_TIMEOUT_MS = 180000  # 3 минуты
# Таймаут перед проверкой Appcharge на основной странице (если FastSpring не открылся)
_FASTSPRING_SHORT_TIMEOUT_MS = 45000  # 45 сек

async def _is_appcharge_checkout(page) -> bool:
    """Проверяет, что на странице открыт checkout Appcharge (не FastSpring)."""
    try:
        text = (await page.evaluate("() => document.body.innerText")).lower()
        url = (page.url or "").lower()
        return (
            "powered by appcharge" in text
            or "appcharge" in text
            or "buy with g pay" in text
            or "appcharge" in url
        )
    except Exception:
        return False


async def _wait_for_fastspring_loaded(page, timeout_ms: int = None) -> list:
    """
    Ждёт пока FastSpring checkout загрузится — либо в iframe, либо прямо на странице.
    На скриншоте форма [Card][PayPal][Google Pay][Amazon Pay] рендерится прямо
    на store.supercell.com, без отдельного iframe.
    Возвращает список загруженных FastSpring frame.
    """
    if timeout_ms is None:
        timeout_ms = _FASTSPRING_IFRAME_TIMEOUT_MS
    logger.info("Ожидание загрузки FastSpring checkout (таймаут %s сек)...", timeout_ms // 1000)
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000

    while asyncio.get_event_loop().time() < deadline:
        # ── Проверка 1: FastSpring форма прямо на текущей странице ───────────
        # Признаки: кнопки [Card][PayPal][Google Pay][Amazon Pay] + цена + "Sold and fulfilled by FastSpring"
        try:
            has_fastspring_form = await page.evaluate("""() => {
                const text = (document.body.innerText || '').toLowerCase();
                const hasFastspring = text.includes('fastspring') || text.includes('sold and fulfilled');
                const hasGooglePay = text.includes('google pay') || text.includes('g pay');
                const hasPrice = !!document.body.innerText.match(/\\$[\\d.]+/);
                const hasPaymentTabs = text.includes('card') && (text.includes('paypal') || text.includes('amazon pay'));
                return (hasFastspring || hasPaymentTabs) && hasGooglePay && hasPrice;
            }""")
            if has_fastspring_form:
                logger.info("FastSpring форма обнаружена прямо на странице (не в iframe): %s", page.url[:80])
                return [page.main_frame]
        except Exception:
            pass

        # ── Проверка 2: FastSpring embedded iframe ─────────────────────────
        frames = _get_fastspring_frames(page)
        # Убираем main_frame из списка — уже проверили выше
        iframe_frames = [f for f in frames if f != page.main_frame]

        if iframe_frames:
            loaded = []
            for frame in iframe_frames:
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
            logger.debug(f"FastSpring iframe найден ({len(iframe_frames)}), ждём контента...")
        else:
            logger.debug("FastSpring iframe ещё не появился, ждём...")

        await page.wait_for_timeout(2000)

    logger.warning("FastSpring checkout не загрузился за отведённое время")
    return []


# Селекторы кнопки оплаты Appcharge: "Pay $0.99" / "Place Your Order" (после выбора плашки Google Pay)
_APPCHARGE_BUY_GPAY_SELECTORS = [
    'button:has-text("Place Your Order")',
    'button:has-text("Place your order")',
    'button:has-text("Pay $")',
    'button:has-text("Pay €")',
    'button:has-text("Pay £")',
    'button:has-text("Buy with G Pay")',
    'button:has-text("Buy with Google Pay")',
    '[role="button"]:has-text("Buy with G Pay")',
    'button:has-text("Pay with G Pay")',
    'button:has-text("Pay with Google Pay")',
    '.gpay-button',
    '[class*="gpay-button"]',
    '[class*="google-pay-button"]',
    'button[type="submit"]:visible',
]


async def select_gpay_and_buy_appcharge(page) -> bool:
    """
    Checkout Appcharge (или на основной странице): выбираем плашку Google Pay,
    ждём прогрузки, нажимаем "Place Your Order" / "Pay $X.XX".
    Откроется окно Sign in → те же шаги, что FastSpring.
    Используется при обнаружении Appcharge или когда FastSpring не открылся.
    Возвращает True, если кнопка оплаты нажата (откроется окно Sign in).

    Flow:
    1. Ищем плашку Google Pay стандартными селекторами
    2. Если не нашли — спрашиваем Claude AI по скриншоту
    3. После клика ждём прогрузки (до 12 сек)
    4. Ищем кнопку Place Your Order стандартными селекторами
    5. Если не нашли — спрашиваем Claude AI по скриншоту
    """
    logger.info("Appcharge: выбор плашки Google Pay → ожидание загрузки → Place Your Order...")
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)
    except Exception:
        pass

    await _accept_cookies_on_page(page)
    await page.wait_for_timeout(2000)

    # Собираем цели: главная страница + все iframe (checkout может быть в любом из них)
    targets = [page]
    try:
        for f in page.frames:
            if f != page.main_frame:
                targets.append(f)
    except Exception:
        pass

    for idx, target in enumerate(targets):
        is_main = target == page
        label = "main" if is_main else f"iframe_{idx}"
        try:
            frame_url = getattr(target, "url", None) or ""
            logger.info("Appcharge: проверяем %s: %s", label, (frame_url or "")[:80])
        except Exception:
            pass

        # ── Шаг 1: Клик на плашку Google Pay ─────────────────────────────────
        # Метод 1: JS точный поиск текста "Google Pay"
        tab_clicked = await _click_fastspring_gpay_tab(target if target != page else page)

        # Метод 2: CSS-селекторы
        if not tab_clicked:
            tab_clicked = await _try_click_in_frame(
                target, _GPAY_TAB_SELECTORS,
                f"Appcharge ({label}): выбрана плашка Google Pay"
            )

        # Метод 3: Claude AI ищет вкладку G Pay по скриншоту
        if not tab_clicked:
            logger.info("Appcharge (%s): стандартные селекторы не нашли G Pay, спрашиваем Claude AI...", label)
            claude_selector = await _claude_find_gpay_selector(
                page,
                context_hint="This is an Appcharge payment checkout page."
            )
            if claude_selector:
                tab_clicked = await _try_click_claude_selector(
                    target, claude_selector,
                    f"Appcharge ({label}): клик по G Pay вкладке"
                )
                if not tab_clicked:
                    # Попробуем на основной странице если искали в iframe
                    tab_clicked = await _try_click_claude_selector(
                        page, claude_selector,
                        f"Appcharge (main fallback): клик по G Pay вкладке"
                    )

        if not tab_clicked:
            continue

        # ── Шаг 2: Ждём прогрузки формы Google Pay ───────────────────────────
        logger.info("Appcharge: Google Pay выбран, ждём прогрузки формы...")
        # Ждём появления кнопки Place Your Order (до 12 сек с проверкой каждые 2 сек)
        pay_button_appeared = False
        for wait_step in range(6):
            await page.wait_for_timeout(2000)
            # Быстрая проверка: появилась ли кнопка
            for quick_sel in ['button:has-text("Place Your Order")', 'button:has-text("Place your order")',
                               'button:has-text("Pay $")', 'button:has-text("Buy with G Pay")']:
                try:
                    loc = target.locator(quick_sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        pay_button_appeared = True
                        logger.info("Appcharge: кнопка оплаты появилась на шаге %d", wait_step + 1)
                        break
                except Exception:
                    continue
            if pay_button_appeared:
                break

        if not pay_button_appeared:
            logger.info("Appcharge: кнопка оплаты не появилась за 12 сек после выбора G Pay, продолжаем попытку...")

        await _screenshot(page, "appcharge_after_gpay_tab")

        # ── Шаг 3: Нажимаем кнопку Place Your Order / Pay ────────────────────
        pay_clicked = await _try_click_in_frame(
            target, _APPCHARGE_BUY_GPAY_SELECTORS,
            f"Appcharge ({label}): нажата кнопка Pay / Place Your Order"
        )
        if not pay_clicked:
            pay_clicked = await _try_click_in_frame(
                target, _GPAY_PAY_BUTTON_SELECTORS,
                f"Appcharge ({label}): нажата кнопка оплаты (fallback)"
            )

        # Fallback: Claude AI ищет кнопку оплаты по скриншоту
        if not pay_clicked:
            logger.info("Appcharge (%s): кнопка оплаты не найдена, спрашиваем Claude AI...", label)
            claude_pay_selector = await _claude_find_pay_button_selector(
                page,
                context_hint="Google Pay tab is selected. Find the 'Place Your Order' or pay button."
            )
            if claude_pay_selector:
                pay_clicked = await _try_click_claude_selector(
                    target, claude_pay_selector,
                    f"Appcharge ({label}): клик по кнопке оплаты"
                )
                if not pay_clicked:
                    pay_clicked = await _try_click_claude_selector(
                        page, claude_pay_selector,
                        f"Appcharge (main fallback): клик по кнопке оплаты"
                    )

        if pay_clicked:
            await _screenshot(page, "appcharge_buy_with_gpay_clicked")
            return True

    logger.warning("Appcharge: плашка Google Pay или кнопка Pay/Place Your Order не найдены ни на странице, ни в iframe")
    await _screenshot(page, "appcharge_buy_gpay_not_found")
    return False


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


async def _click_fastspring_gpay_tab(page_or_frame) -> bool:
    """
    Специальная функция для клика по вкладке Google Pay в форме FastSpring.
    Использует JavaScript для точного поиска — находит элемент платёжного
    переключателя содержащий текст 'Google Pay', но НЕ являющийся контейнером.
    Возвращает True если клик выполнен.
    """
    try:
        clicked = await page_or_frame.evaluate("""() => {
            // Ищем все элементы содержащие текст "Google Pay" или "G Pay"
            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_ELEMENT,
                null
            );
            const candidates = [];
            let node;
            while (node = walker.nextNode()) {
                const text = (node.textContent || '').trim();
                const ownText = Array.from(node.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join('');
                // Точный текст "Google Pay" или "G Pay" в своих текстовых узлах
                if (ownText === 'Google Pay' || ownText === 'G Pay' ||
                    text === 'Google Pay' || text === 'G Pay') {
                    const rect = node.getBoundingClientRect();
                    // Не контейнер: элемент небольшой и кликабельный
                    if (rect.width < 300 && rect.height < 200 && rect.width > 0) {
                        candidates.push(node);
                    }
                }
            }
            // Кликаем по первому подходящему (кнопка/label/div-плашка)
            for (const el of candidates) {
                const tag = el.tagName.toLowerCase();
                const style = window.getComputedStyle(el);
                const isClickable = (
                    tag === 'button' || tag === 'label' || tag === 'a' ||
                    tag === 'li' || el.getAttribute('role') === 'tab' ||
                    el.getAttribute('role') === 'option' ||
                    el.getAttribute('role') === 'radio' ||
                    style.cursor === 'pointer'
                );
                if (isClickable) {
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    return el.tagName + ':' + (el.textContent || '').trim().slice(0, 30);
                }
            }
            // Fallback: кликаем по любому кандидату
            if (candidates.length > 0) {
                candidates[0].scrollIntoView({block: 'center'});
                candidates[0].click();
                return 'fallback:' + candidates[0].tagName;
            }
            return null;
        }""")
        if clicked:
            logger.info(f"FastSpring Google Pay вкладка нажата через JS: {clicked}")
            return True
    except Exception as e:
        logger.debug(f"JS клик по Google Pay вкладке: {e}")
    return False


async def select_gpay_tab_and_pay(page, timeout_ms: int = 90000) -> bool:
    """
    Основная функция: находит FastSpring форму (на странице или в iframe),
    кликает вкладку Google Pay тремя методами (JS / CSS / Claude AI),
    ждёт появления кнопки "Pay $X.XX" и нажимает её.
    Параллельно проверяет Appcharge checkout.
    Возвращает True если кнопка оплаты нажата.
    """
    logger.info("═══════════════════════════════════════════")
    logger.info("═══ select_gpay_tab_and_pay START ═══")
    logger.info(f"═══ URL: {page.url}")
    logger.info("═══════════════════════════════════════════")

    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)
    except Exception:
        pass

    await _accept_cookies_on_page(page)
    await page.wait_for_timeout(500)
    await _screenshot(page, "gpay_checkout_start")

    # ── Диагностика страницы ───────────────────────────────────────────────────
    try:
        page_text_lower = (await page.evaluate("() => document.body.innerText")).lower()
        frames_count = len(page.frames)
        logger.info(f"[ДИАГНОСТИКА] Кол-во frames на странице: {frames_count}")
        logger.info(f"[ДИАГНОСТИКА] Есть 'fastspring': {'fastspring' in page_text_lower}")
        logger.info(f"[ДИАГНОСТИКА] Есть 'google pay': {'google pay' in page_text_lower}")
        logger.info(f"[ДИАГНОСТИКА] Есть 'appcharge': {'appcharge' in page_text_lower}")
        logger.info(f"[ДИАГНОСТИКА] Есть 'buy with g pay': {'buy with g pay' in page_text_lower}")
        for i, f in enumerate(page.frames):
            try:
                logger.info(f"[FRAME {i}] url={f.url[:100]}")
            except Exception:
                pass
    except Exception as diag_e:
        logger.debug(f"[ДИАГНОСТИКА] ошибка: {diag_e}")

    # ── Сразу проверяем Appcharge ──────────────────────────────────────────────
    logger.info("[ШАГ 1] Проверяем Appcharge checkout...")
    if await _is_appcharge_checkout(page):
        logger.info("[ШАГ 1] ✓ Обнаружен checkout Appcharge → запускаем select_gpay_and_buy_appcharge")
        appcharge_ok = await select_gpay_and_buy_appcharge(page)
        if appcharge_ok:
            logger.info("[ШАГ 1] ✓ Appcharge: кнопка оплаты нажата")
            return True
        logger.info("[ШАГ 1] ✗ Appcharge: кнопка не нажата, продолжаем поиск FastSpring...")
    else:
        logger.info("[ШАГ 1] Appcharge не обнаружен, продолжаем с FastSpring")

    # ── Ожидание FastSpring + периодическая проверка Appcharge ────────────────
    logger.info("[ШАГ 2] Ожидание FastSpring checkout...")
    fastspring_wait_ms = min(timeout_ms, _FASTSPRING_SHORT_TIMEOUT_MS)
    check_interval_ms = 5000
    elapsed_ms = 0
    loaded_frames = []

    while elapsed_ms < fastspring_wait_ms and not loaded_frames:
        logger.info(f"[ШАГ 2] Итерация {elapsed_ms // 1000}с / {fastspring_wait_ms // 1000}с — вызываем _wait_for_fastspring_loaded...")
        loaded_frames = await _wait_for_fastspring_loaded(page, timeout_ms=check_interval_ms)
        if loaded_frames:
            logger.info(f"[ШАГ 2] ✓ FastSpring загружен, frames: {len(loaded_frames)}")
            break

        logger.info(f"[ШАГ 2] FastSpring не найден, проверяем Appcharge (elapsed={elapsed_ms}ms)...")
        if await _is_appcharge_checkout(page):
            logger.info("[ШАГ 2] Appcharge обнаружен во время ожидания FastSpring")
            appcharge_ok = await select_gpay_and_buy_appcharge(page)
            if appcharge_ok:
                return True

        elapsed_ms += check_interval_ms

    if not loaded_frames:
        logger.warning(f"[ШАГ 2] ✗ FastSpring не открылся за {fastspring_wait_ms // 1000}с")
        logger.info("[ШАГ 2] Финальная попытка Appcharge/прямой поиск G Pay...")
        appcharge_ok = await select_gpay_and_buy_appcharge(page)
        if appcharge_ok:
            return True

        logger.info("[ШАГ 2] Последний шанс — прямой локатор Google Pay на странице...")
        try:
            loc = page.locator('button:has-text("G Pay"), button:has-text("Google Pay")').first
            cnt = await loc.count()
            logger.info(f"[ШАГ 2] Локатор Google Pay нашёл: {cnt} элементов")
            if cnt > 0:
                loaded_frames = [page.main_frame]
            else:
                await _screenshot(page, "fastspring_gpay_not_found")
                logger.error("[ШАГ 2] ✗ Google Pay не найден нигде — выходим")
                return False
        except Exception as e:
            logger.error(f"[ШАГ 2] Исключение при поиске Google Pay: {e}")
            await _screenshot(page, "fastspring_gpay_not_found")
            return False

    await _screenshot(page, "fastspring_loaded")
    logger.info(f"[ШАГ 3] FastSpring форма готова. Frames для обработки: {len(loaded_frames)}")

    # ── Клик по вкладке Google Pay ─────────────────────────────────────────────
    tab_click_max_attempts = 4
    pay_click_attempts = [(4000, "1"), (6000, "2"), (8000, "3"), (10000, "4")]

    for fi, frame in enumerate(loaded_frames):
        frame_url = getattr(frame, "url", None) or page.url
        logger.info(f"[ШАГ 3] Обрабатываем frame[{fi}]: {(frame_url or '')[:80]}")
        tab_clicked = False

        # Метод 1: JS TreeWalker — ищет точный текст "Google Pay" в DOM
        logger.info(f"[ШАГ 3.1] Метод JS: _click_fastspring_gpay_tab (frame[{fi}])...")
        tab_clicked = await _click_fastspring_gpay_tab(frame)
        if tab_clicked:
            logger.info(f"[ШАГ 3.1] ✓ JS клик по Google Pay вкладке выполнен (frame[{fi}])")
        elif frame != page.main_frame:
            logger.info(f"[ШАГ 3.1] JS не нашёл в iframe, пробуем на основной странице...")
            tab_clicked = await _click_fastspring_gpay_tab(page)
            if tab_clicked:
                logger.info("[ШАГ 3.1] ✓ JS клик по Google Pay вкладке выполнен (main page)")

        # Метод 2: CSS-селекторы
        if not tab_clicked:
            logger.info(f"[ШАГ 3.2] Метод CSS: перебор _GPAY_TAB_SELECTORS ({len(_GPAY_TAB_SELECTORS)} шт)...")
            for attempt in range(1, tab_click_max_attempts + 1):
                logger.info(f"[ШАГ 3.2] CSS попытка {attempt}/{tab_click_max_attempts} в frame[{fi}]...")
                tab_clicked = await _try_click_in_frame(
                    frame, _GPAY_TAB_SELECTORS,
                    f"[CSS] Google Pay вкладка (frame[{fi}], попытка {attempt})"
                )
                if not tab_clicked and frame != page.main_frame:
                    logger.info(f"[ШАГ 3.2] CSS попытка {attempt} на main page...")
                    tab_clicked = await _try_click_in_frame(
                        page, _GPAY_TAB_SELECTORS,
                        f"[CSS] Google Pay вкладка (main, попытка {attempt})"
                    )
                if tab_clicked:
                    logger.info(f"[ШАГ 3.2] ✓ CSS клик по Google Pay вкладке (попытка {attempt})")
                    break
                if attempt < tab_click_max_attempts:
                    logger.info(f"[ШАГ 3.2] Ждём 3 сек перед попыткой {attempt + 1}...")
                    await page.wait_for_timeout(3000)

        # Метод 3: Claude AI
        if not tab_clicked:
            logger.info("[ШАГ 3.3] Метод Claude AI: делаем скриншот и спрашиваем...")
            claude_tab_sel = await _claude_find_gpay_selector(
                page,
                context_hint="FastSpring checkout on store.supercell.com. 4 tabs: Card, PayPal, Google Pay, Amazon Pay. Return selector for Google Pay tab."
            )
            logger.info(f"[ШАГ 3.3] Claude AI предложил: {claude_tab_sel!r}")
            if claude_tab_sel:
                tab_clicked = await _try_click_claude_selector(frame, claude_tab_sel, "[Claude] Google Pay вкладка frame")
                if not tab_clicked:
                    tab_clicked = await _try_click_claude_selector(page, claude_tab_sel, "[Claude] Google Pay вкладка main")
                if tab_clicked:
                    logger.info("[ШАГ 3.3] ✓ Claude AI клик выполнен")

        if not tab_clicked:
            logger.error(f"[ШАГ 3] ✗ Все методы не нашли Google Pay вкладку в frame[{fi}] — пропускаем")
            continue

        logger.info(f"[ШАГ 3] ✓ Google Pay вкладка НАЖАТА в frame[{fi}] — ждём кнопку оплаты...")
        await _screenshot(page, f"fastspring_gpay_tab_clicked_{fi}")

        # ── Ждём кнопку оплаты ────────────────────────────────────────────────
        pay_appeared = False
        for wait_step in range(8):
            await page.wait_for_timeout(2000)
            for quick_sel in [
                'button:has-text("Pay $")', 'button:has-text("Place Your Order")',
                'button:has-text("Place your order")', '.gpay-button',
            ]:
                try:
                    targets_check = ([frame, page] if frame != page.main_frame else [page])
                    for t in targets_check:
                        loc = t.locator(quick_sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            logger.info(f"[ШАГ 4] ✓ Кнопка оплаты появилась на шаге {wait_step+1}: {quick_sel!r}")
                            pay_appeared = True
                            break
                    if pay_appeared:
                        break
                except Exception:
                    continue
            if pay_appeared:
                break
        if not pay_appeared:
            logger.warning("[ШАГ 4] Кнопка оплаты не появилась за 16 сек, всё равно пробуем нажать...")
        await _screenshot(page, "fastspring_after_gpay_tab")

        # ── Нажимаем кнопку оплаты ────────────────────────────────────────────
        pay_clicked = False
        for wait_after_ms, lbl in pay_click_attempts:
            logger.info(f"[ШАГ 4] Попытка {lbl} нажать кнопку оплаты (Pay/Place Your Order)...")
            targets_to_try = ([frame, page] if frame != page.main_frame else [page])
            for t in targets_to_try:
                pay_clicked = await _try_click_in_frame(
                    t, _GPAY_PAY_BUTTON_SELECTORS,
                    f"[Pay] кнопка оплаты FastSpring (попытка {lbl})"
                )
                if pay_clicked:
                    break
            if pay_clicked:
                break
            logger.info(f"[ШАГ 4] Кнопка не найдена, ждём {wait_after_ms // 1000}с...")
            await page.wait_for_timeout(wait_after_ms)
            await _screenshot(page, f"fastspring_gpay_retry_{lbl}")

        if not pay_clicked:
            logger.info("[ШАГ 4] Claude AI: ищем кнопку оплаты по скриншоту...")
            claude_pay_sel = await _claude_find_pay_button_selector(
                page,
                context_hint="FastSpring checkout. Google Pay is selected. Find 'Pay $0.99' or 'Place Your Order' button."
            )
            logger.info(f"[ШАГ 4] Claude AI кнопка оплаты: {claude_pay_sel!r}")
            if claude_pay_sel:
                pay_clicked = await _try_click_claude_selector(frame, claude_pay_sel, "[Claude] Pay кнопка frame")
                if not pay_clicked:
                    pay_clicked = await _try_click_claude_selector(page, claude_pay_sel, "[Claude] Pay кнопка main")

        if pay_clicked:
            await _screenshot(page, "fastspring_gpay_pay_clicked")
            logger.info(f"[ШАГ 4] ✓ Кнопка оплаты НАЖАТА — frame[{fi}]")
            return True

        logger.error(f"[ШАГ 4] ✗ Кнопка оплаты не найдена в frame[{fi}] после всех попыток")

    await _screenshot(page, "fastspring_gpay_not_found")
    logger.error("[ИТОГ] ✗ select_gpay_tab_and_pay: не удалось нажать Google Pay и кнопку оплаты")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Шаг 2: Логин в Google в popup
# ──────────────────────────────────────────────────────────────────────────────

def _is_google_block_page(page_text: str) -> bool:
    """Проверяет, показала ли Google страницу «This browser or app may not be secure»."""
    t = (page_text or "").lower()
    return (
        "couldn't sign you in" in t
        or "this browser or app may not be secure" in t
    )


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

    current_url = popup_page.url
    logger.info(f"URL popup Google: {current_url}")

    if "accounts.google.com" not in current_url and "signin" not in current_url:
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

    # Задержка между нажатиями клавиш (мс) — имитация человека, меньше детект
    type_delay_min, type_delay_max = 80, 180

    # ── Email ─────────────────────────────────────────────────────────────────
    email_selectors = ['input[type="email"]', 'input[name="identifier"]', '#identifierId']
    email_entered = False
    for sel in email_selectors:
        try:
            el = await popup_page.wait_for_selector(sel, timeout=45000)
            if el:
                await el.click()
                await _delay(popup_page, 400, 800)
                # Посимвольный ввод с задержкой вместо fill() — меньше шанс блокировки
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

    if not email_entered:
        logger.warning("Поле email не найдено в popup Google")
        return False, None

    await _delay(popup_page, 600, 1200)
    for sel in ['#identifierNext', 'button:has-text("Next")', 'button[type="submit"]']:
        try:
            loc = popup_page.locator(sel).first
            if await loc.count() > 0:
                await loc.click(timeout=15000)
                logger.info("Next после email нажат")
                break
        except Exception:
            continue

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
            el = await popup_page.wait_for_selector(sel, timeout=45000)
            if el:
                await el.click()
                await _delay(popup_page, 400, 800)
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
    for sel in ['#passwordNext', 'button:has-text("Next")', 'button[type="submit"]']:
        try:
            loc = popup_page.locator(sel).first
            if await loc.count() > 0:
                await loc.click(timeout=15000)
                logger.info("Next после пароля нажат")
                break
        except Exception:
            continue

    await popup_page.wait_for_timeout(15000)

    # ── 2-Step Verification: прокрутка вниз → "Try another way" → выбор "8-digit backup code" ─
    backup_code = _parse_first_backup_code(backup_codes)
    if backup_code:
        try:
            body_text = (await popup_page.evaluate("() => document.body.innerText")).lower()
            current_url = (popup_page.url or "").lower()
            is_2sv_challenge = (
                "challenge" in current_url
                or "2-step verification" in body_text
                or "2-step verification" in body_text.replace("-", " ")
                or "двухэтапн" in body_text
                or "подтвердит" in body_text
                or "резервн" in body_text
                or "open the youtube app" in body_text
                or "open the google app" in body_text
                or "sent a notification" in body_text
            )
            if is_2sv_challenge:
                logger.info("Обнаружена страница 2-Step Verification, прокрутка вниз и поиск «Try another way»...")
                await popup_page.evaluate("window.scrollBy(0, 400)")
                await popup_page.wait_for_timeout(1000)
                await popup_page.evaluate("window.scrollBy(0, 400)")
                await popup_page.wait_for_timeout(800)
                await popup_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await popup_page.wait_for_timeout(1000)

                try_another_way_selectors = [
                    'a:has-text("Try another way")',
                    'span:has-text("Try another way")',
                    '[role="link"]:has-text("Try another way")',
                    'button:has-text("Try another way")',
                    'a:has-text("Try a different way")',
                    'a:has-text("Выбрать другой способ")',
                    'span:has-text("Выбрать другой способ")',
                    'a:has-text("Другой способ")',
                    'span:has-text("Другой способ")',
                ]
                try_another_clicked = False
                for wait_attempt in range(8):
                    for sel in try_another_way_selectors:
                        try:
                            loc = popup_page.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.scroll_into_view_if_needed()
                                await _delay(popup_page, 400, 800)
                                await loc.click(timeout=25000)
                                try_another_clicked = True
                                logger.info("Нажато «Try another way»")
                                break
                        except Exception:
                            continue
                    if try_another_clicked:
                        break
                    await popup_page.wait_for_timeout(2000)
                if not try_another_clicked:
                    try:
                        for text in ["Try another way", "Try a different way", "Выбрать другой способ", "Другой способ"]:
                            el = popup_page.get_by_text(text, exact=False).first
                            if await el.count() > 0 and await el.is_visible():
                                await el.scroll_into_view_if_needed()
                                await el.click(timeout=25000)
                                try_another_clicked = True
                                logger.info("Нажато «Try another way» (get_by_text)")
                                break
                    except Exception:
                        pass

                await popup_page.wait_for_timeout(12000)

                # ── Диагностика страницы после "Try another way" ──────────────
                try:
                    _diag_url = popup_page.url
                    _diag_text = (await popup_page.evaluate("() => document.body.innerText")).lower()
                    logger.info(f"[backup-select] URL после Try another way: {_diag_url[:80]}")
                    logger.info(f"[backup-select] Есть 'backup': {'backup' in _diag_text}")
                    logger.info(f"[backup-select] Есть '8-digit': {'8-digit' in _diag_text}")
                    logger.info(f"[backup-select] Есть 'резервн': {'резервн' in _diag_text}")
                    # Логируем весь кликабельный текст на странице для диагностики
                    _clickable = await popup_page.evaluate("""() => {
                        const els = document.querySelectorAll('a, button, [role="option"], [role="listitem"], li, div[tabindex]');
                        return Array.from(els).map(e => e.tagName + ':' + (e.textContent || '').trim().slice(0, 60)).filter(t => t.length > 2);
                    }""")
                    logger.info(f"[backup-select] Кликабельные элементы: {_clickable[:15]}")
                except Exception as _de:
                    logger.debug(f"[backup-select] диагностика: {_de}")

                # Выбор входа по 8-значному резервному коду (после "Try another way")
                # Google показывает список методов — карточки/опции с текстом
                backup_option_selectors = [
                    # Точные — специфичные для Google UI
                    '[data-challengetype="12"]',          # Google challengetype для backup code
                    '[data-challengetype="13"]',
                    'li:has-text("Enter one of your 8-digit backup codes")',
                    'li:has-text("backup code")',
                    'li:has-text("Backup code")',
                    '[role="link"]:has-text("Enter one of your 8-digit backup codes")',
                    '[role="link"]:has-text("backup code")',
                    '[role="option"]:has-text("backup code")',
                    '[role="option"]:has-text("Backup code")',
                    '[role="listitem"]:has-text("backup code")',
                    'div[tabindex]:has-text("backup code")',
                    'div[tabindex]:has-text("Backup code")',
                    # Ссылки и span
                    'a:has-text("Enter one of your 8-digit backup codes")',
                    'a:has-text("8-digit backup code")',
                    'a:has-text("backup code")',
                    'a:has-text("Backup code")',
                    'span:has-text("Enter one of your 8-digit backup codes")',
                    'span:has-text("8-digit backup code")',
                    'span:has-text("backup code")',
                    # Другие тексты Google
                    'a:has-text("Use a backup code")',
                    '[role="option"]:has-text("Use a backup code")',
                    # Русские варианты
                    'a:has-text("Введите один из резервных кодов")',
                    'li:has-text("резервн")',
                    'div[tabindex]:has-text("резервн")',
                    'span:has-text("Введите один из резервных кодов")',
                    'a:has-text("Резервный код")',
                    'span:has-text("Резервный код")',
                    'div:has-text("8-значн")',
                    'a:has-text("8-значн")',
                ]
                backup_option_clicked = False
                for wait_attempt in range(8):
                    for sel in backup_option_selectors:
                        try:
                            loc = popup_page.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.scroll_into_view_if_needed()
                                await _delay(popup_page, 400, 800)
                                await loc.click(timeout=25000)
                                backup_option_clicked = True
                                logger.info(f"Выбран вход по 8-значному резервному коду: {sel}")
                                break
                        except Exception:
                            continue
                    if backup_option_clicked:
                        break
                    # get_by_text fallback
                    if not backup_option_clicked:
                        try:
                            for text in [
                                "Enter one of your 8-digit backup codes", "8-digit backup code",
                                "Use a backup code", "backup code", "Backup code",
                                "Введите один из резервных кодов", "Резервный код", "8-значн",
                            ]:
                                el = popup_page.get_by_text(text, exact=False).first
                                if await el.count() > 0 and await el.is_visible():
                                    await el.scroll_into_view_if_needed()
                                    await el.click(timeout=25000)
                                    backup_option_clicked = True
                                    logger.info(f"Выбран вход по 8-значному коду (get_by_text): {text!r}")
                                    break
                        except Exception:
                            pass
                    if backup_option_clicked:
                        break
                    # JS fallback — ищем по тексту в DOM напрямую
                    if not backup_option_clicked:
                        try:
                            js_clicked = await popup_page.evaluate("""() => {
                                const keywords = ['backup code', 'backup codes', '8-digit', 'резервн', '8-значн'];
                                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
                                let node;
                                while (node = walker.nextNode()) {
                                    const text = (node.textContent || '').toLowerCase().trim();
                                    const tag = node.tagName.toLowerCase();
                                    const rect = node.getBoundingClientRect();
                                    if (rect.width === 0 || rect.height === 0) continue;
                                    const isClickable = (
                                        tag === 'a' || tag === 'button' || tag === 'li' ||
                                        node.getAttribute('role') === 'option' ||
                                        node.getAttribute('role') === 'link' ||
                                        node.getAttribute('role') === 'listitem' ||
                                        node.getAttribute('tabindex') !== null
                                    );
                                    if (!isClickable) continue;
                                    for (const kw of keywords) {
                                        if (text.includes(kw) && text.length < 200) {
                                            node.click();
                                            return tag + ': ' + text.slice(0, 60);
                                        }
                                    }
                                }
                                return null;
                            }""")
                            if js_clicked:
                                backup_option_clicked = True
                                logger.info(f"Выбран вход по 8-значному коду (JS): {js_clicked}")
                        except Exception as _je:
                            logger.debug(f"JS backup option click: {_je}")
                    if backup_option_clicked:
                        break
                    logger.debug(f"backup option: попытка {wait_attempt + 1}/8 не удалась, ждём 2 сек...")
                    await popup_page.wait_for_timeout(2000)

                # ── Ждём страницу "Enter one of your 8-digit backup codes" и вводим код ──
                # Эта страница появляется ПОСЛЕ клика по опции "8-digit backup code"
                if backup_option_clicked and backup_code:
                    logger.info("Ожидание страницы ввода резервного кода...")
                    _bcode_input_selectors = [
                        'input[type="tel"]',
                        'input[name="backupCode"]',
                        'input[type="number"]',
                        'input[inputmode="numeric"]',
                        'input[autocomplete="one-time-code"]',
                        'input[aria-label*="backup"]',
                        'input[aria-label*="Backup"]',
                        'input[placeholder*="backup"]',
                        'input[placeholder*="code"]',
                        'input[id*="backup"]',
                        'input[id*="code"]',
                        'input[type="text"]',
                    ]
                    backup_input_el = None
                    # Ждём до 20 сек появления поля ввода кода
                    for _bi in range(10):
                        await popup_page.wait_for_timeout(2000)
                        try:
                            body_now = (await popup_page.evaluate("() => document.body.innerText")).lower()
                            is_backup_input_page = (
                                "enter one of your 8-digit" in body_now
                                or "backup code" in body_now
                                or "8-digit" in body_now
                                or "резервн" in body_now
                                or ("введите" in body_now and "код" in body_now)
                            )
                            if is_backup_input_page:
                                logger.info(f"Страница ввода резервного кода обнаружена (шаг {_bi + 1})")
                                for bsel in _bcode_input_selectors:
                                    try:
                                        el = popup_page.locator(bsel).first
                                        if await el.count() > 0 and await el.is_visible():
                                            backup_input_el = el
                                            logger.info(f"Поле ввода резервного кода: {bsel}")
                                            break
                                    except Exception:
                                        continue
                                if backup_input_el:
                                    break
                        except Exception as _be:
                            logger.debug(f"backup-wait шаг {_bi + 1}: {_be}")

                    if backup_input_el:
                        await backup_input_el.click()
                        await _delay(popup_page, 400, 700)
                        await popup_page.keyboard.type(
                            backup_code,
                            delay=random.randint(type_delay_min, type_delay_max),
                        )
                        await _delay(popup_page, 500, 1000)
                        logger.info("Введён 8-значный резервный код (после Try another way)")
                        # Нажимаем Next/Verify
                        _next_sels = [
                            'button:has-text("Next")', 'button:has-text("Verify")',
                            'button:has-text("Далее")', 'button:has-text("Подтвердить")',
                            'button[type="submit"]', '#identifierNext',
                            '[role="button"]:has-text("Next")', '[role="button"]:has-text("Verify")',
                        ]
                        for _ns in _next_sels:
                            try:
                                _nloc = popup_page.locator(_ns).first
                                if await _nloc.count() > 0 and await _nloc.is_visible():
                                    await _nloc.scroll_into_view_if_needed()
                                    await _nloc.click(timeout=15000)
                                    logger.info(f"Next/Verify нажат после ввода резервного кода: {_ns}")
                                    break
                            except Exception:
                                continue
                        await popup_page.wait_for_timeout(8000)
                        # Ждём редирект на pay.google.com и кнопку "Оплатить"
                        logger.info("Ожидание экрана оплаты (pay.google.com) после ввода резервного кода...")
                        pay_screen_seen = False
                        for _pi in range(30):
                            await popup_page.wait_for_timeout(1000)
                            try:
                                current_url = (popup_page.url or "").lower()
                                _body = (await popup_page.evaluate("() => document.body.innerText")).lower()
                                is_pay_screen = (
                                    "pay.google.com" in current_url
                                    or "оплатить" in _body
                                    or "total" in _body and ("mastercard" in _body or "visa" in _body or "pay" in _body)
                                    or "place order" in _body
                                )
                                if is_pay_screen:
                                    pay_screen_seen = True
                                    logger.info(f"Экран оплаты pay.google.com появился (шаг {_pi + 1}), URL: {popup_page.url[:80]}")
                                    await popup_page.wait_for_timeout(2000)
                                    await _screenshot(popup_page, "google_pay_ready_to_confirm")
                                    await _confirm_payment_in_popup(popup_page)
                                    break
                            except Exception:
                                pass
                        if not pay_screen_seen:
                            logger.warning("Экран оплаты не появился за 30 сек после ввода резервного кода")
                    else:
                        logger.warning("Поле ввода резервного кода не найдено за 20 сек — продолжаем к fallback")
                        await popup_page.wait_for_timeout(5000)
                else:
                    await popup_page.wait_for_timeout(12000)
        except Exception as e:
            logger.debug("Шаг 2-Step Verification (Try another way): %s", e)

    # При таймауте на любом шаге не прерываем — продолжаем до последнего

    # ── Проверка: запрос 8-значного резервного кода (backup code) ─────────────
    code_input_selectors = [
        'input[type="tel"]',
        'input[name="backupCode"]',
        'input[type="number"]',
        'input[inputmode="numeric"]',
        'input[autocomplete="one-time-code"]',
        'input[aria-label*="backup"]',
        'input[aria-label*="код"]',
        'input[placeholder*="backup"]',
        'input[placeholder*="код"]',
        'input[placeholder*="code"]',
        'input[id*="backup"]',
        'input[id*="code"]',
        'input[type="text"]',
    ]
    code_entered = False
    if backup_code:
        try:
            code_input = None
            for sel in code_input_selectors:
                try:
                    code_input = await popup_page.wait_for_selector(sel, timeout=8000)
                    if code_input and await code_input.is_visible():
                        break
                except Exception:
                    continue
            if code_input:
                body_text = (await popup_page.evaluate("() => document.body.innerText")).lower()
                is_backup_page = (
                    "backup" in body_text or "резервн" in body_text or "8-digit" in body_text
                    or "8 digit" in body_text or "верификац" in body_text or "verification code" in body_text
                    or "код" in body_text
                )
                if is_backup_page or await code_input.is_visible():
                    await code_input.click()
                    await _delay(popup_page, 400, 700)
                    await popup_page.keyboard.type(
                        backup_code,
                        delay=random.randint(type_delay_min, type_delay_max),
                    )
                    await _delay(popup_page, 500, 1000)
                    code_entered = True
                    logger.info("Введён 8-значный резервный код")
            if code_entered:
                await _delay(popup_page, 600, 1200)
                next_verify_selectors = [
                    'button:has-text("Next")', 'button:has-text("Verify")', 'button:has-text("Далее")',
                    'button:has-text("Подтвердить")', 'button[type="submit"]',
                    '#identifierNext', '[role="button"]:has-text("Next")', '[role="button"]:has-text("Verify")',
                ]
                next_verify_clicked = False
                for sel in next_verify_selectors:
                    try:
                        loc = popup_page.locator(sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            await loc.scroll_into_view_if_needed()
                            await loc.click(timeout=25000)
                            next_verify_clicked = True
                            logger.info("Next/Verify после резервного кода нажат")
                            break
                    except Exception:
                        continue
                if not next_verify_clicked:
                    import re
                    try:
                        btn = popup_page.get_by_role("button", name=re.compile(r"next|verify|далее|подтвердить", re.I)).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click(timeout=25000)
                            next_verify_clicked = True
                            logger.info("Next/Verify нажат (get_by_role)")
                    except Exception:
                        pass
                if not next_verify_clicked:
                    for txt in ["Next", "Verify", "Далее", "Подтвердить"]:
                        try:
                            el = popup_page.get_by_text(txt, exact=False).first
                            if await el.count() > 0 and await el.is_visible():
                                await el.click(timeout=25000)
                                next_verify_clicked = True
                                logger.info("Next/Verify нажат (get_by_text)")
                                break
                        except Exception:
                            continue
                await popup_page.wait_for_timeout(8000)
                # После Next/Verify ждём экран оплаты Google Pay и нажимаем Оплатить/Pay
                logger.info("Ожидание экрана оплаты (Оплатить/Pay) после верификации резервного кода...")
                pay_screen_seen = False
                for _ in range(30):
                    await popup_page.wait_for_timeout(1000)
                    body_lower = (await popup_page.evaluate("() => document.body.innerText")).lower()
                    if "pay" in body_lower or "оплатить" in body_lower or "place order" in body_lower or "g pay" in body_lower:
                        pay_screen_seen = True
                        await popup_page.wait_for_timeout(2000)
                        break
                if pay_screen_seen:
                    await _confirm_payment_in_popup(popup_page)
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
# Шаг 3: Подтверждение оплаты в popup Google Pay
# ──────────────────────────────────────────────────────────────────────────────

async def _click_pay_button_once(popup_page, confirm_selectors, re_module) -> bool:
    """Одна попытка нажать кнопку Оплатить/Pay. Возвращает True если клик выполнен."""
    # Даём странице время отрисовать кнопку (pay.google.com динамический)
    await popup_page.wait_for_timeout(3000)
    for _wait_step in range(10):
        for sel in confirm_selectors:
            try:
                loc = popup_page.locator(sel).first
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed()
                    await _delay(popup_page, 300, 600)
                    try:
                        await loc.click(timeout=15000)
                    except Exception:
                        await loc.click(timeout=10000, force=True)
                    logger.info(f"Кнопка 'Оплатить'/'Pay' нажата: {sel}")
                    return True
            except Exception:
                continue
        if _wait_step < 9:
            await popup_page.wait_for_timeout(2000)
    for name_pattern in [re_module.compile(r"оплатить|pay|confirm|continue|подтвердить", re_module.I)]:
        try:
            btn = popup_page.get_by_role("button", name=name_pattern).first
            if await btn.count() > 0:
                await btn.scroll_into_view_if_needed()
                await _delay(popup_page, 300, 600)
                try:
                    await btn.click(timeout=15000)
                except Exception:
                    await btn.click(timeout=10000, force=True)
                logger.info("Кнопка 'Оплатить'/'Pay' нажата: get_by_role(button)")
                return True
        except Exception:
            continue
    # Запасной вариант: клик через JavaScript (кнопка может быть в shadow DOM или перекрыта)
    try:
        clicked = await popup_page.evaluate("""
            () => {
                function findAndClickInRoot(root) {
                    const byJsname = root.querySelector('button[jsname="LgbsSe"]');
                    if (byJsname) { byJsname.click(); return true; }
                    const byClass = root.querySelector('button.VfPpkd-LgbsSe');
                    if (byClass) { byClass.click(); return true; }
                    const buttons = root.querySelectorAll('button');
                    for (const b of buttons) {
                        const t = (b.textContent || '').trim();
                        if (t === 'Оплатить' || t === 'Pay' || t.includes('Оплатить')) {
                            b.click();
                            return true;
                        }
                    }
                    const span = root.querySelector('span.VfPpkd-vQzf8d');
                    if (span && span.textContent && span.textContent.includes('Оплатить')) {
                        const btn = span.closest('button');
                        if (btn) { btn.click(); return true; }
                    }
                    return false;
                }
                if (findAndClickInRoot(document)) return true;
                const all = document.querySelectorAll('*');
                for (let i = 0; i < all.length; i++) {
                    if (all[i].shadowRoot && findAndClickInRoot(all[i].shadowRoot)) return true;
                }
                return false;
            }
        """)
        if clicked:
            logger.info("Кнопка 'Оплатить'/'Pay' нажата: JavaScript click")
            return True
    except Exception as e:
        logger.debug("JS клик по кнопке Оплатить: %s", e)
    return False


async def _payment_page_has_error_async(popup_page) -> bool:
    """Проверяет, есть ли на странице ошибка после нажатия (например REQUEST_TIMEOUT)."""
    try:
        body = (await popup_page.evaluate("() => document.body.innerText")).lower()
    except Exception:
        return False
    # Конкретные сообщения Google Pay при сбое оплаты
    errors = ("request_timeout", "request timeout", "connection error", "something went wrong")
    return any(e in body for e in errors)


async def _confirm_payment_in_popup(popup_page) -> bool:
    """
    Нажимает кнопку подтверждения оплаты в popup Google Pay.
    Экран: pay.google.com — кнопка "Оплатить" / "Pay".
    При появлении ошибки (например REQUEST_TIMEOUT) перезагружает страницу и повторяет до 3 попыток.
    """
    import re as re_module
    logger.info("Подтверждение оплаты в Google Pay popup...")

    try:
        await popup_page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass

    logger.info(f"URL перед подтверждением: {popup_page.url[:80]}")
    await _screenshot(popup_page, "google_pay_confirm_popup")

    # Кнопка "Оплатить" на pay.google.com — Material Design: jsname="LgbsSe", span с текстом "Оплатить"
    confirm_selectors = [
        'button[jsname="LgbsSe"]',
        'button.VfPpkd-LgbsSe',
        'button:has(span:has-text("Оплатить"))',
        'button:has(span.VfPpkd-vQzf8d:has-text("Оплатить"))',
        'button:has-text("Оплатить")',
        'button:has-text("Pay")',
        '[role="button"]:has-text("Оплатить")',
        '[role="button"]:has-text("Pay")',
        'button:has-text("Pay with G Pay")',
        'button:has-text("Pay with Google Pay")',
        'button:has-text("Continue")',
        'button:has-text("Confirm")',
        'button:has-text("Place order")',
        'button:has-text("Buy")',
        'button:has-text("Подтвердить")',
        'button:has-text("Оплатить с G Pay")',
        '[class*="pay-button"]',
        '[class*="payButton"]',
        '[class*="VfPpkd-LgbsSe"]',
        '[jsname*="pay"]',
        '[data-value*="pay"]',
        'button[type="submit"]',
        '[class*="confirm"]',
        '[data-testid*="pay"]',
        '[data-testid*="confirm"]',
        'div[role="button"]:has-text("Pay")',
        'span[role="button"]:has-text("Pay")',
    ]

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            logger.info("Перезагрузка страницы Google Pay перед повторной попыткой нажатия 'Оплатить' (%s/3)...", attempt)
            try:
                await popup_page.reload(wait_until="domcontentloaded", timeout=60000)
                await popup_page.wait_for_timeout(5000)
            except Exception as e:
                logger.warning("Ошибка перезагрузки popup: %s", e)
            await _screenshot(popup_page, f"google_pay_confirm_retry_{attempt}")

        clicked = await _click_pay_button_once(popup_page, confirm_selectors, re_module)
        if not clicked:
            if attempt == max_attempts:
                await _screenshot(popup_page, "google_pay_confirm_failed")
                logger.warning("Кнопка подтверждения оплаты ('Оплатить'/'Pay') не найдена после %s попыток", max_attempts)
                return False
            continue

        await popup_page.wait_for_timeout(6000)
        if await _payment_page_has_error_async(popup_page):
            logger.warning(
                "После нажатия 'Оплатить' обнаружена ошибка (например REQUEST_TIMEOUT), попытка %s/%s",
                attempt, max_attempts,
            )
            if attempt < max_attempts:
                continue
        return True

    return True


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
            try:
                text = (await page.evaluate("() => document.body.innerText")).lower()
            except Exception:
                text = ""

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
    """Очищает cookies браузерного контекста после оплаты (в т.ч. Google), чтобы не оставлять сессию."""
    logger.info("Выход из Google аккаунта (очистка cookies)...")
    try:
        if getattr(browser, "context", None):
            cookies = await browser.context.cookies()
            google_cookies = [c for c in cookies if "google" in c.get("domain", "")]
            if google_cookies:
                await browser.context.clear_cookies()
                logger.info("Очищены cookies контекста (в т.ч. Google)")
            else:
                logger.info("Google cookies не найдены")
    except Exception as e:
        logger.warning("Ошибка при выходе из Google (игнорируем): %s", e)


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
    Полный flow оплаты через Google Pay (FastSpring или Appcharge checkout).

    Appcharge обрабатывается параллельно с FastSpring:
    - Проверяется немедленно при старте
    - Периодически (каждые 5 сек) во время ожидания FastSpring
    - При неудаче стандартных селекторов — Claude AI анализирует скриншот

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
        popup_page = None
        clicked = False
        try:
            async with page.context.expect_page(timeout=150000) as popup_info:
                clicked = await select_gpay_tab_and_pay(page, timeout_ms=180000)
            if clicked:
                popup_page = await popup_info.value
                logger.info(f"Открылся popup Google Pay: {popup_page.url}")
        except Exception as e:
            logger.info(f"Popup не открылся или таймаут ({type(e).__name__})")
            # clicked сохраняет значение из select_gpay_tab_and_pay

        if not clicked:
            result["error"] = (
                "Не удалось кликнуть G Pay вкладку или кнопку оплаты "
                "(Place Your Order / Buy with G Pay). FastSpring или Appcharge не обнаружены."
            )
            await _screenshot(page, "gpay_click_failed")
            return result

        result["google_pay_clicked"] = True
        await page.wait_for_timeout(2000)

        # Popup flow: [экран G Pay "Оплатить"] → клик → [sign-in] → логин → [подтверждение] → клик
        target_page = popup_page if popup_page else page

        if popup_page:
            try:
                await popup_page.wait_for_load_state("domcontentloaded", timeout=60000)
            except Exception:
                pass

            current_url = (popup_page.url or "").lower()
            is_signin = "accounts.google.com" in current_url or "signin" in current_url

            # Шаг 2a: Если popup ещё на экране G Pay (не sign-in) — нажимаем "Оплатить"/Pay, после чего откроется sign-in
            signin_page = None  # страница с accounts.google.com (может быть тот же popup или новое окно)
            if not is_signin:
                logger.info("Popup открыт на экране G Pay, нажимаем 'Оплатить' / Pay...")
                first_pay_clicked = await _confirm_payment_in_popup(popup_page)
                if first_pay_clicked:
                    logger.info("Кнопка оплаты нажата, ожидание перехода на страницу входа Google...")
                    # Ждём sign-in: либо навигация в том же popup, либо новое окно (до 90 сек)
                    for _ in range(90):
                        await popup_page.wait_for_timeout(1000)
                        try:
                            current_url = (popup_page.url or "").lower()
                            if "accounts.google.com" in current_url or "signin" in current_url:
                                signin_page = popup_page
                                logger.info("Открылась страница входа Google (sign-in) в том же popup")
                                break
                        except Exception:
                            pass
                        # Проверяем все страницы контекста — sign-in мог открыться в новом окне
                        if signin_page is None and browser.context:
                            for p in browser.context.pages:
                                try:
                                    u = (p.url or "").lower()
                                    if "accounts.google.com" in u or ("signin" in u and "google" in u):
                                        signin_page = p
                                        logger.info("Найдена страница входа Google в новом окне: %s", p.url[:80])
                                        break
                                except Exception:
                                    continue
                        if signin_page is not None:
                            break
                    if signin_page is None:
                        logger.warning("Страница sign-in не обнаружена за 90 сек (popup и все окна проверены)")

            # Страница для логина: найденная sign-in или текущий popup если уже на sign-in
            if signin_page is None and popup_page:
                try:
                    u = (popup_page.url or "").lower()
                    if "accounts.google.com" in u or "signin" in u:
                        signin_page = popup_page
                except Exception:
                    pass

            # Шаг 2b: Логин в Google (на signin_page или popup_page). При таймауте не выходим — идём дальше.
            if (signin_page or popup_page) and email and app_password:
                login_page = signin_page or popup_page
                try:
                    target_url = (login_page.url or "").lower()
                    if "accounts.google.com" in target_url or "signin" in target_url:
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
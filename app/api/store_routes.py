"""API routes для работы с магазином Supercell Store."""

import asyncio
import re
import random
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict
from loguru import logger
from app.config import settings
from app.core.browser_automation import BrowserAutomation
from app.core.ai_product_search import AIProductSearch
from app.core.proxy_manager import proxy_manager
from app.api.supercell_auth_routes import _accept_cookies

router = APIRouter()

MAX_BLOCK_RETRIES = 3


async def _find_and_click_product(browser: "BrowserAutomation", product_name: str) -> bool:
    """
    Поиск и клик по карточке товара через Playwright (без AI).
    Использует scrollIntoView перед кликом — работает с длинными страницами.
    Возвращает True если удалось кликнуть по товару.
    """
    import re as _re

    page = browser.page
    if not page:
        return False

    # Ждём полной загрузки страницы
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass

    name_lower = product_name.lower().strip()
    # Числовая часть (например "80" из "80 Gems")
    num_match = _re.search(r"\d+", product_name)
    num_str = num_match.group() if num_match else ""
    # Ключевое слово (например "gems")
    keyword = _re.sub(r"\d+\s*", "", name_lower).strip().rstrip("s")  # "gems" → "gem"

    logger.info(f"Поиск товара '{product_name}' (num={num_str}, keyword={keyword})")

    # ── Стратегия 1: Playwright locator с точным текстом ──────────────────────
    exact_selectors = [
        f'text="{product_name}"',
        f'text={product_name}',
    ]
    for sel in exact_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.scroll_into_view_if_needed()
                await page.wait_for_timeout(500)
                bb = await loc.bounding_box()
                if bb:
                    logger.info(f"Стратегия 1 (exact text): '{sel}' at ({bb['x']:.0f},{bb['y']:.0f})")
                    await loc.click(timeout=5000)
                    return True
        except Exception:
            pass

    # ── Стратегия 2: get_by_text regex ────────────────────────────────────────
    try:
        pattern = _re.compile(rf"\b{_re.escape(num_str)}\s*{_re.escape(keyword)}s?\b", _re.I) if num_str else _re.compile(_re.escape(name_lower), _re.I)
        loc = page.get_by_text(pattern)
        count = await loc.count()
        logger.debug(f"Стратегия 2 (get_by_text regex): найдено {count} элементов")
        for i in range(min(count, 8)):
            el = loc.nth(i)
            try:
                await el.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                bb = await el.bounding_box()
                if bb and bb["width"] > 20 and bb["height"] > 10:
                    logger.info(f"Стратегия 2 (get_by_text regex) #{i}: ({bb['x']:.0f},{bb['y']:.0f}) size={bb['width']:.0f}x{bb['height']:.0f}")
                    await el.click(timeout=5000)
                    return True
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"Стратегия 2: {e}")

    # ── Стратегия 3: JS — найти элемент, прокрутить, кликнуть ────────────────
    # Ищем самый компактный элемент содержащий "80" + "gem"
    try:
        handle = await page.evaluate_handle(
            """([num, kw, fullName]) => {
                const lower = fullName.toLowerCase();
                let best = null, bestLen = Infinity;
                for (const el of document.querySelectorAll('*')) {
                    const t = (el.innerText || el.textContent || '').toLowerCase().trim();
                    const hasNum = num ? t.includes(num) : true;
                    const hasKw  = kw  ? t.includes(kw)  : true;
                    if (hasNum && hasKw && t.length < bestLen && t.length < lower.length * 8) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 20 && r.height > 10) {
                            best = el;
                            bestLen = t.length;
                        }
                    }
                }
                return best;
            }""",
            [num_str, keyword, name_lower],
        )
        el = handle.as_element()
        if el:
            await el.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)
            bb = await el.bounding_box()
            if bb:
                logger.info(f"Стратегия 3 (JS scrollIntoView): ({bb['x']:.0f},{bb['y']:.0f}) size={bb['width']:.0f}x{bb['height']:.0f}")
                await el.click(timeout=5000)
                return True
    except Exception as e:
        logger.debug(f"Стратегия 3: {e}")

    # ── Стратегия 4: CSS :has-text локаторы ──────────────────────────────────
    css_candidates = [
        f'[class*="product"]:has-text("{product_name}")',
        f'[class*="card"]:has-text("{product_name}")',
        f'[class*="item"]:has-text("{product_name}")',
        f'[class*="shop"]:has-text("{product_name}")',
        f'li:has-text("{product_name}")',
        f'article:has-text("{product_name}")',
    ]
    for css in css_candidates:
        try:
            loc = page.locator(css).first
            if await loc.count() > 0:
                await loc.scroll_into_view_if_needed()
                await page.wait_for_timeout(400)
                bb = await loc.bounding_box()
                if bb:
                    logger.info(f"Стратегия 4 (CSS has-text): '{css}' at ({bb['x']:.0f},{bb['y']:.0f})")
                    await loc.click(timeout=5000)
                    return True
        except Exception:
            continue

    logger.warning(f"Все стратегии не нашли карточку '{product_name}'")
    return False


class PurchaseRequest(BaseModel):
    """Запрос на покупку товара в магазине."""

    email: EmailStr
    verification_code: Optional[str] = None  # Код верификации (если уже известен)
    email_password: Optional[str] = None  # Пароль для доступа к email (для получения кода)
    game: str = "brawl-stars"  # Игра: "brawl-stars" или "clash-royale"
    product_name: str = "80 Gems"  # Название товара для поиска
    product_type: str = "gems"  # Тип товара: "gems", "cards", etc.


@router.post("/supercell/purchase")
async def purchase_product(request: PurchaseRequest):
    """
    Покупка товара в Supercell Store.

    На Windows Patchright требует ProactorEventLoop (create_subprocess_exec).
    Uvicorn использует SelectorEventLoop, поэтому весь flow запускается
    в отдельном потоке со своим ProactorEventLoop.
    """
    import sys as _sys
    if _sys.platform == "win32":
        def _run_in_proactor():
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_purchase_flow(request))
            finally:
                loop.close()
        return await asyncio.get_event_loop().run_in_executor(None, _run_in_proactor)
    return await _purchase_flow(request)


async def _purchase_flow(request: PurchaseRequest):
    """Вся логика покупки. На Windows вызывается из потока с ProactorEventLoop."""
    browser = BrowserAutomation()
    session_id = f"purchase_{request.email.replace('@', '_at_')}_{request.game}"
    last_error = None

    for block_attempt in range(MAX_BLOCK_RETRIES):
        try:
            logger.info(
                f"Начало покупки товара '{request.product_name}' в {request.game} для {request.email}"
            )

            # Шаг 1: Авторизация в Supercell Store (порядок как в full-auth: store → cookies → вход)
            logger.info("Шаг 1: Авторизация в Supercell Store...")
            await browser.start()

            # Как в full-auth: переход на store, пауза, принятие cookies
            await browser.page.goto(
                "https://store.supercell.com",
                wait_until="domcontentloaded",
                timeout=60000
            )
            await browser.page.wait_for_timeout(3000)
            cookies_ok = await _accept_cookies(browser)
            if not cookies_ok:
                await browser.page.wait_for_timeout(2500)
                await _accept_cookies(browser)
            await browser.human_like_delay(2000, 3000)

            current_url = browser.page.url
            page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")
            is_logged_in = (
                "store.supercell.com" in current_url
                and "login" not in current_url.lower()
                and ("logout" in page_text or "sign out" in page_text or "account" in page_text)
            )

            if not is_logged_in:
                logger.info("Требуется авторизация, выполняем вход в том же браузере...")
                from app.core.email_code_reader import EmailCodeReader

                login_selectors = [
                    'a:has-text("Log in")',
                    'a:has-text("Sign in")',
                    'button:has-text("Log in")',
                    '[href*="login"]',
                    'text=Log in',
                ]
                login_clicked = False
                for selector in login_selectors:
                    try:
                        el = await browser.page.query_selector(selector)
                        if el and await el.is_visible():
                            await el.click()
                            login_clicked = True
                            logger.info(f"Кнопка входа найдена: {selector}")
                            break
                    except Exception:
                        continue
                if not login_clicked:
                    try:
                        await browser.page.click('text=Log in', timeout=5000)
                        login_clicked = True
                    except Exception:
                        pass

                if login_clicked:
                    logger.info("Переход на страницу авторизации (ждём редирект)...")
                    try:
                        await browser.page.wait_for_url(
                            lambda url: "accounts.supercell.com" in url or "id.supercell.com" in url,
                            timeout=15000,
                        )
                        logger.info(f"Редирект выполнен: {browser.page.url}")
                    except Exception:
                        logger.warning("Редирект не произошёл, переходим на accounts.supercell.com/login")
                        try:
                            await browser.page.goto(
                                "https://accounts.supercell.com/login",
                                wait_until="domcontentloaded",
                                timeout=30000,
                            )
                        except Exception as e:
                            logger.debug(f"Ошибка перехода: {e}")
                else:
                    logger.warning("Кнопка входа не найдена, переходим на accounts.supercell.com/login")
                    try:
                        await browser.page.goto(
                            "https://accounts.supercell.com/login",
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
                    except Exception as e:
                        logger.debug(f"Ошибка перехода: {e}")

                await browser.page.wait_for_load_state("domcontentloaded", timeout=15000)
                await browser.human_like_delay(800, 1500)
                await _accept_cookies(browser)
                await browser.human_like_delay(500, 1000)

                current_url = browser.page.url
                if "id.supercell.com" in current_url:
                    for sel in ['button:has-text("LOG IN")', 'button:has-text("Log in")', 'a:has-text("Log in")']:
                        try:
                            el = await browser.page.wait_for_selector(sel, timeout=4000)
                            if el and await el.is_visible():
                                await el.click()
                                logger.info(f"Кнопка входа на странице id нажата: {sel}")
                                await browser.human_like_delay(2000, 3000)
                                await _accept_cookies(browser)
                                break
                        except Exception:
                            continue

                await browser.human_like_delay(6000, 11000)
                try:
                    for _ in range(random.randint(2, 4)):
                        rx = random.randint(150, 700)
                        ry = random.randint(200, 500)
                        await browser.page.mouse.move(rx, ry)
                        await browser.page.wait_for_timeout(random.randint(400, 900))
                    await browser.page.evaluate("window.scrollBy({ top: 60, behavior: 'smooth' })")
                    await browser.page.wait_for_timeout(random.randint(500, 1200))
                except Exception:
                    pass
                await browser.human_like_delay(1000, 2000)
                try:
                    page_text_pre = (await browser.page.evaluate("() => document.body.innerText")).lower()
                    if "something went wrong" in page_text_pre or "try again later" in page_text_pre:
                        logger.warning("«Something went wrong» на странице логина — перезагрузка")
                        await browser.page.reload(wait_until="domcontentloaded", timeout=60000)
                        await browser.human_like_delay(8000, 12000)
                        await _accept_cookies(browser)
                        await browser.human_like_delay(1000, 2000)
                except Exception:
                    pass

                email_selectors = [
                    'input[type="email"]',
                    'input[name="email"]',
                    'input[name="username"]',
                    'input[name="identifier"]',
                    'input[id*="email"]',
                    'input[id*="username"]',
                    'input[id*="identifier"]',
                    'input[placeholder*="email" i]',
                    'input[placeholder*="Email" i]',
                    'input[aria-label*="email" i]',
                ]
                email_input = None
                found_email_selector = None
                for i, selector in enumerate(email_selectors):
                    timeout_ms = 30000 if i == 0 else 10000
                    try:
                        email_input = await browser.page.wait_for_selector(selector, timeout=timeout_ms)
                        if email_input:
                            found_email_selector = selector
                            logger.info(f"Найдено поле email: {selector}")
                            break
                    except Exception:
                        continue

                if not email_input:
                    logger.info("Поле email не найдено, повторно проверяем баннер cookies...")
                    await _accept_cookies(browser)
                    await browser.human_like_delay(2000, 3000)
                    for selector in email_selectors:
                        try:
                            email_input = await browser.page.wait_for_selector(selector, timeout=8000)
                            if email_input:
                                found_email_selector = selector
                                break
                        except Exception:
                            continue

                if not email_input:
                    page_text = (await browser.page.evaluate("() => document.body.innerText")).lower()
                    if "something went wrong" in page_text or "try again later" in page_text:
                        raise Exception(
                            "Supercell ID вернул «Something went wrong». Попробуйте позже или с другим прокси."
                        )
                    raise Exception(
                        "Поле email не найдено на странице входа. Проверьте скриншот; возможна ошибка Supercell ID или блокировка."
                    )

                page_text_before = (await browser.page.evaluate("() => document.body.innerText")).lower()
                if "blocked your login request" in page_text_before or "unusual activity" in page_text_before:
                    raise Exception(
                        "Supercell заблокировал вход (unusual activity). Отключите прокси (PROXY_ENABLED=false) или попробуйте позже."
                    )

                await browser.human_like_delay(800, 1500)
                try:
                    el = await browser.page.query_selector(found_email_selector)
                    if el:
                        box = await el.bounding_box()
                        if box:
                            await browser.page.mouse.move(
                                box["x"] + box["width"] * 0.3,
                                box["y"] + box["height"] * 0.5
                            )
                            await browser.page.wait_for_timeout(random.randint(200, 400))
                except Exception:
                    pass
                await browser.human_like_type(found_email_selector, request.email, delay_between_chars=130)
                await browser.human_like_delay(800, 1500)
                entered_email = await browser.page.input_value(found_email_selector)
                if entered_email != request.email:
                    await browser.page.keyboard.press("Control+a")
                    await browser.page.wait_for_timeout(random.randint(50, 150))
                    await browser.page.keyboard.press("Delete")
                    await browser.human_like_delay(200, 400)
                    await browser.human_like_type(found_email_selector, request.email, delay_between_chars=130)
                    await browser.human_like_delay(500, 1000)

                page_text_before_click = (await browser.page.evaluate("() => document.body.innerText")).lower()
                if "blocked your login request" in page_text_before_click or "unusual activity" in page_text_before_click:
                    raise Exception(
                        "Supercell заблокировал вход (unusual activity) на шаге ввода email. "
                        "Отключите прокси (PROXY_ENABLED=false) или попробуйте резидентный прокси."
                    )

                form_scoped = [
                    f"form:has({found_email_selector}) button[type='submit']",
                    f"form:has({found_email_selector}) button:has-text('LOG IN')",
                    f"form:has({found_email_selector}) button:has-text('Log in')",
                    f"form:has({found_email_selector}) button",
                ]
                continue_selectors = form_scoped + [
                    'button:has-text("Send code")', 'button:has-text("Get code")',
                    'button:has-text("Next")', 'button:has-text("Continue")',
                    'button:has-text("Log in")', 'button:has-text("Sign in")',
                    'button[type="submit"]', 'input[type="submit"]',
                ]

                if getattr(settings, "CAPTCHA_2CAPTCHA_API_KEY", ""):
                    try:
                        from app.core.recaptcha_solver import solve_recaptcha_enterprise
                        captcha_token = await solve_recaptcha_enterprise(
                            api_key=settings.CAPTCHA_2CAPTCHA_API_KEY,
                            page_url=browser.page.url or "https://accounts.supercell.com/login",
                            timeout=120,
                        )
                        if captcha_token:
                            await browser.page.evaluate(
                                """(token) => {
                                    window.__2captchaToken = token;
                                    var check = setInterval(function() {
                                        if (window.grecaptcha && window.grecaptcha.enterprise) {
                                            clearInterval(check);
                                            var real = window.grecaptcha.enterprise.execute;
                                            if (real && !real.__patched) {
                                                window.grecaptcha.enterprise.execute = function() {
                                                    return Promise.resolve(window.__2captchaToken || null);
                                                };
                                                window.grecaptcha.enterprise.execute.__patched = true;
                                            }
                                        }
                                    }, 100);
                                    setTimeout(function() { clearInterval(check); }, 5000);
                                }""",
                                captcha_token,
                            )
                            await browser.human_like_delay(500, 1000)
                            try:
                                await browser.page.evaluate(
                                    """(token) => {
                                        var form = document.querySelector('form');
                                        if (form && !form.querySelector('input[name="g-recaptcha-response"]')) {
                                            var inp = document.createElement('input');
                                            inp.type = 'hidden';
                                            inp.name = 'g-recaptcha-response';
                                            inp.value = token;
                                            form.appendChild(inp);
                                        }
                                    }""",
                                    captcha_token,
                                )
                            except Exception:
                                pass
                            logger.info("2Captcha: токен reCAPTCHA подставлен перед LOG IN")
                        else:
                            logger.warning("2Captcha не вернул токен — продолжаем без него")
                    except Exception as e:
                        logger.debug(f"2Captcha при покупке: {e}")

                await browser.human_like_delay(1000, 2000)

                continue_clicked = False
                for selector in continue_selectors:
                    try:
                        element = await browser.page.wait_for_selector(selector, timeout=3000)
                        if not element or not await element.is_visible():
                            continue
                        box = await element.bounding_box()
                        if not box:
                            continue
                        target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
                        target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
                        try:
                            email_box = await browser.page.query_selector(found_email_selector)
                            if email_box:
                                eb = await email_box.bounding_box()
                                start_x = eb["x"] + eb["width"] * 0.5 if eb else target_x - 50
                                start_y = eb["y"] + eb["height"] * 0.5 if eb else target_y - 80
                            else:
                                start_x, start_y = target_x - 50, target_y - 80
                        except Exception:
                            start_x, start_y = target_x - 50, target_y - 80
                        mid_x = (start_x + target_x) / 2 + random.uniform(-20, 20)
                        mid_y = (start_y + target_y) / 2 + random.uniform(-15, 15)
                        steps = random.randint(12, 20)
                        for i in range(steps):
                            t = (i + 1) / steps
                            bx = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * mid_x + t ** 2 * target_x
                            by = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * mid_y + t ** 2 * target_y
                            await browser.page.mouse.move(bx + random.uniform(-1, 1), by + random.uniform(-1, 1))
                            await browser.page.wait_for_timeout(random.randint(8, 20))
                        await browser.page.wait_for_timeout(random.randint(80, 180))
                        await browser.page.mouse.click(target_x, target_y, delay=random.randint(60, 130))
                        continue_clicked = True
                        logger.info(f"Кнопка LOG IN нажата (mouse, Безье): {selector}")
                        break
                    except Exception as e:
                        logger.debug(f"Селектор LOG IN {selector}: {e}")
                        continue

                if not continue_clicked:
                    try:
                        await browser.page.keyboard.press("Tab")
                        await browser.page.wait_for_timeout(random.randint(150, 300))
                        await browser.page.keyboard.press("Enter")
                        continue_clicked = True
                        logger.info("Кнопка LOG IN нажата через Tab+Enter")
                    except Exception:
                        pass

                await browser.human_like_delay(1000, 2000)
                await _accept_cookies(browser)
                await browser.human_like_delay(1500, 2500)
                page_text_after = (await browser.page.evaluate("() => document.body.innerText")).lower()
                if "blocked your login request" in page_text_after or "unusual activity" in page_text_after:
                    raise Exception(
                        "Supercell заблокировал вход после отправки email (unusual activity). "
                        "Попробуйте: PROXY_ENABLED=false, 2Captcha (CAPTCHA_2CAPTCHA_API_KEY), резидентный прокси или BROWSER_USE_PATCHRIGHT=true."
                    )

                verification_code = request.verification_code
                code_entered_manually = False

                # Режим ручного ввода: если код не передан — ждём 2 минуты, пока пользователь введёт код вручную
                if not verification_code and not request.email_password:
                    logger.info("Ожидание до 2 минут — введите код верификации вручную в браузере.")
                    manual_wait_seconds = 120
                    deadline = asyncio.get_event_loop().time() + manual_wait_seconds
                    code_input_selectors = [
                        'input[type="tel"]',
                        'input[autocomplete="one-time-code"]',
                        'input[inputmode="numeric"]',
                        'input[placeholder*="123" i]',
                    ]
                    while asyncio.get_event_loop().time() < deadline:
                        try:
                            btn_loc = browser.page.get_by_role("button", name=re.compile(r"continue", re.I))
                            if await btn_loc.count() > 0:
                                btn = btn_loc.first
                                aria = (await btn.get_attribute("aria-disabled")) or ""
                                disabled = False
                                try:
                                    disabled = await btn.is_disabled()
                                except Exception:
                                    disabled = "true" in aria.strip().lower()
                                if not disabled:
                                    await btn.click()
                                    logger.info("Код введён вручную, нажата кнопка CONTINUE.")
                                    code_entered_manually = True
                                    break
                        except Exception:
                            pass
                        try:
                            for sel in code_input_selectors:
                                inp = await browser.page.query_selector(sel)
                                if inp:
                                    val = await inp.get_attribute("value") or ""
                                    if len(val.replace(" ", "").replace("-", "")) >= 6:
                                        btn_loc = browser.page.get_by_role("button", name=re.compile(r"continue", re.I))
                                        if await btn_loc.count() > 0:
                                            await btn_loc.first.click()
                                            logger.info("Обнаружено 6 цифр в поле кода, нажата кнопка CONTINUE.")
                                            code_entered_manually = True
                                    break
                            if code_entered_manually:
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(1)
                    if not code_entered_manually:
                        raise Exception(
                            "Истекло 2 минуты ожидания ручного ввода кода. "
                            "Введите код в браузере в течение 2 минут или передайте verification_code / email_password."
                        )
                else:
                    # Получаем код верификации из запроса или email
                    if not verification_code and request.email_password:
                        logger.info("Ожидание кода верификации из email...")
                        email_reader = EmailCodeReader(request.email, request.email_password)
                        verification_code = email_reader.get_supercell_code(timeout=120)

                    if not verification_code:
                        raise Exception(
                            "Код верификации не предоставлен. "
                            "Введите код верификации из письма Supercell или предоставьте email_password."
                        )

                    verification_code = verification_code.replace(" ", "").replace("-", "").strip()
                    code_selectors = [
                        'input[type="tel"]',
                        'input[autocomplete="one-time-code"]',
                        'input[inputmode="numeric"]',
                        'input[placeholder*="123" i]',
                    ]
                    code_input = None
                    for selector in code_selectors:
                        try:
                            code_input = await browser.page.wait_for_selector(selector, timeout=30000)
                            if code_input:
                                break
                        except Exception:
                            continue

                    if code_input:
                        await code_input.fill("")
                        await code_input.type(verification_code, delay=80)
                        await browser.human_like_delay(500, 1000)
                        await code_input.focus()
                        await browser.page.keyboard.press("Enter")
                        await browser.human_like_delay(2000, 3000)

                    await browser.page.wait_for_timeout(5000)
                    try:
                        await browser.page.wait_for_url(
                            lambda url: "store.supercell.com" in url and "login" not in url.lower(),
                            timeout=30000,
                        )
                    except Exception:
                        pass

                logger.info("Авторизация завершена, продолжаем покупку...")
                await browser.human_like_delay(2000, 3000)
        
            # Шаг 2: Переход в магазин игры
            logger.info(f"Шаг 2: Переход в магазин {request.game}...")
            await browser.navigate_to_store(request.game)
            await browser.human_like_delay(3000, 5000)
        
            # Скриншот страницы магазина
            await browser.take_screenshot(f"store_{request.game}_{session_id}.png")

            # Шаг 3: Поиск товара через Playwright (без AI)
            logger.info(f"Шаг 3: Поиск товара '{request.product_name}' через Playwright...")
            product_info = None  # AI отключён

            # Шаг 4: Клик по карточке товара
            logger.info("Шаг 4: Добавление товара в корзину...")
            clicked = await _find_and_click_product(browser, request.product_name)

            if not clicked:
                await browser.take_screenshot(f"product_not_found_{session_id}.png")
                raise Exception(
                    f"Товар '{request.product_name}' не найден на странице магазина {request.game}. "
                    "Возможные причины:\n"
                    "1. Товар отсутствует в магазине\n"
                    "2. Товар имеет другое название\n"
                    "3. Страница магазина не загрузилась полностью"
                )
        
            # После клика по карточке — ждём появления кнопки "Buy" / "Add to Cart"
            await browser.human_like_delay(1500, 2500)
            await browser.take_screenshot(f"after_card_click_{session_id}.png")

            # Кнопки покупки в модальном окне (в порядке приоритета)
            buy_btn_selectors = [
                'button:has-text("Buy")',
                'button:has-text("Add to Cart")',
                'button:has-text("Add To Cart")',
                'button:has-text("Purchase")',
                'button:has-text("Купить")',
                '[class*="buy-button"]:visible',
                '[class*="buyButton"]:visible',
                '[class*="add-to-cart"]:visible',
                '[class*="addToCart"]:visible',
                '[data-testid*="buy"]:visible',
                '[data-testid*="add-to-cart"]:visible',
            ]
            cart_btn_clicked = False
            for sel in buy_btn_selectors:
                try:
                    loc = browser.page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.scroll_into_view_if_needed()
                        await browser.page.wait_for_timeout(300)
                        await loc.click(timeout=5000)
                        cart_btn_clicked = True
                        logger.info(f"Нажата кнопка покупки: {sel}")
                        break
                except Exception:
                    continue

            if not cart_btn_clicked:
                logger.info("Отдельная кнопка 'Buy' не найдена — клик по карточке мог сразу открыть форму оплаты")

            # Ждём реакции страницы
            await browser.human_like_delay(2000, 3500)
            await browser.take_screenshot(f"after_add_to_cart_{session_id}.png")

            # Проверяем результат: URL или текст страницы
            current_url = browser.page.url
            page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")

            in_cart = (
                "cart" in current_url.lower()
                or "checkout" in current_url.lower()
                or "payment" in current_url.lower()
                or "order" in current_url.lower()
                or "cart" in page_text
                or "checkout" in page_text
                or "payment" in page_text
                or "order summary" in page_text
                or "your order" in page_text
            )

            # Также считаем успехом: кнопка "Buy" была нажата
            added = in_cart or cart_btn_clicked
            if cart_btn_clicked and not in_cart:
                logger.info("Кнопка 'Buy' нажата, ожидаем подтверждения корзины...")
                await browser.human_like_delay(2000, 3000)
                current_url = browser.page.url
                page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")
                in_cart = (
                    "cart" in current_url.lower()
                    or "checkout" in current_url.lower()
                    or "payment" in current_url.lower()
                    or "cart" in page_text
                    or "checkout" in page_text
                    or "payment" in page_text
                )
                added = in_cart or cart_btn_clicked

            if not added:
                logger.warning("Не удалось подтвердить добавление товара в корзину")
        
            # Шаг 5: Переход на окно оформления заказа (checkout), если ещё не там
            checkout_opened = False
            if added:
                page_text_check = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")
                has_checkout_ui = (
                    "checkout" in page_text_check or
                    "payment" in page_text_check or
                    "pay" in page_text_check or
                    "card" in page_text_check
                )
                if "checkout" in current_url.lower() or "payment" in current_url.lower():
                    checkout_opened = True
                    logger.info("Уже на странице checkout/payment")
                elif has_checkout_ui:
                    # Модальное окно оплаты уже открыто
                    checkout_opened = True
                else:
                    # Пробуем нажать Checkout / Proceed to checkout / View cart → Checkout
                    checkout_selectors = [
                        'a:has-text("Checkout")',
                        'button:has-text("Checkout")',
                        'a:has-text("Proceed to checkout")',
                        'button:has-text("Proceed to checkout")',
                        'a:has-text("View cart")',
                        'button:has-text("View cart")',
                        'text=Checkout',
                        'text=Proceed to checkout',
                        'text=View cart',
                        '[class*="checkout"]',
                        '[data-testid*="checkout"]',
                    ]
                    for sel in checkout_selectors:
                        try:
                            el = await browser.page.query_selector(sel)
                            if el and await el.is_visible():
                                await el.click()
                                logger.info(f"Переход к оформлению заказа: {sel}")
                                await browser.human_like_delay(2000, 4000)
                                checkout_opened = True
                                break
                        except Exception:
                            continue
                    if checkout_opened:
                        await browser.take_screenshot(f"checkout_{session_id}.png")
        
            result = {
                "success": True,
                "session_id": session_id,
                "email": request.email,
                "game": request.game,
                "product_name": request.product_name,
                "product_info": {
                    "found": True,
                    "price": product_info.get("price") if product_info else None,
                    "confidence": product_info.get("confidence") if product_info else None,
                    "description": product_info.get("description") if product_info else request.product_name,
                },
                "added_to_cart": added,
                "checkout_opened": checkout_opened,
                "screenshot": f"after_add_to_cart_{session_id}.png",
                "checkout_screenshot": f"checkout_{session_id}.png" if checkout_opened else None,
                "url": browser.page.url,
                "message": (
                    f"Товар '{request.product_name}' добавлен в корзину, окно оформления заказа открыто"
                    if (added and checkout_opened)
                    else (f"Товар '{request.product_name}' добавлен в корзину" if added else "Товар найден, но статус корзины не подтверждён")
                ),
                "proxy_used": browser.current_proxy is not None,
                "proxy_server": browser.current_proxy.get("server") if browser.current_proxy else None,
            }

            try:
                video_path = await browser.close()
                if video_path:
                    result["video"] = video_path
            except Exception as close_err:
                logger.debug(f"Ошибка при закрытии браузера: {close_err}")

            return result
        
        except Exception as e:
            last_error = e
            logger.error(f"Ошибка покупки товара: {e}")
            err_lower = str(e).lower()
            block_phrases = ("unusual activity", "blocked your login", "blocked", "blocked your login request")
            is_block = any(p in err_lower for p in block_phrases)
            if (
                is_block
                and getattr(browser, "current_proxy", None)
                and block_attempt < MAX_BLOCK_RETRIES - 1
            ):
                logger.warning(
                    f"Блокировка Supercell (unusual activity), повтор с новым IP "
                    f"(попытка {block_attempt + 1}/{MAX_BLOCK_RETRIES})..."
                )
                proxy_manager.mark_proxy_failed(browser.current_proxy)
                try:
                    await browser.close()
                except Exception:
                    pass
                continue

            screenshot_path = None
            try:
                if browser.page:
                    screenshot_path = await browser.take_screenshot(
                        f"purchase_error_{session_id}.png"
                    )
            except Exception:
                pass
            video_path = None
            try:
                video_path = await browser.close()
            except Exception:
                pass
            detail = {
                "error": str(e),
                "screenshot": str(screenshot_path) if screenshot_path else None,
                "proxy_used": getattr(browser, "current_proxy", None) is not None,
                "proxy_server": browser.current_proxy.get("server") if getattr(browser, "current_proxy", None) else None,
            }
            if video_path:
                detail["video"] = video_path
            if "timed_out" in err_lower or "err_timed_out" in err_lower or "err_connection" in err_lower:
                detail["hint"] = (
                    "Прокси не успел загрузить страницу. Попробуйте PROXY_ENABLED=false или проверьте прокси."
                )
            if is_block:
                detail["hint"] = (
                    "Supercell заблокировал вход. Попробуйте: PROXY_ENABLED=false, "
                    "2Captcha (CAPTCHA_2CAPTCHA_API_KEY), BROWSER_USE_PATCHRIGHT=true или резидентный прокси."
                )
            raise HTTPException(status_code=500, detail=detail)

    if last_error:
        raise HTTPException(status_code=500, detail={"error": str(last_error)})

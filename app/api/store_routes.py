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
    
    Процесс:
    1. Авторизация в Supercell Store (если не авторизован)
    2. Переход в магазин игры (Brawl Stars / Clash Royale)
    3. Поиск товара с помощью AI
    4. Добавление товара в корзину
    5. Переход на окно оформления заказа (checkout)
    
    Args:
        request: Данные для покупки
        
    Returns:
        Результат покупки
    """
    browser = BrowserAutomation()
    ai_search = AIProductSearch()
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
        
            # Скриншот страницы магазина игры для AI (Claude ищет 80 Gems)
            await browser.take_screenshot(f"store_{request.game}_{session_id}.png")
        
            # Шаг 3: Поиск товара (80 Gems) с помощью AI — смотрим и нажимаем через Claude
            logger.info(f"Шаг 3: Поиск товара '{request.product_name}' с помощью AI...")
            page_content = await browser.get_page_content()
        
            product_info = await ai_search.find_product(
                page_content,
                request.product_name,
                request.product_type
            )
        
            if not product_info or not product_info.get("found"):
                await browser.take_screenshot(f"product_not_found_{session_id}.png")
                raise Exception(
                    f"Товар '{request.product_name}' не найден на странице магазина {request.game}. "
                    "Возможные причины:\n"
                    "1. Товар отсутствует в магазине\n"
                    "2. Товар имеет другое название\n"
                    "3. Страница магазина не загрузилась полностью"
                )
        
            logger.info(
                f"Товар найден: {product_info.get('description', 'N/A')} "
                f"(confidence: {product_info.get('confidence', 0):.2f})"
            )
        
            # Шаг 4: Добавление товара в корзину
            logger.info("Шаг 4: Добавление товара в корзину...")
        
            # Пробуем кликнуть по кнопке покупки
            button_text = product_info.get("button_text", "Buy")
            clicked = await browser.click_element_by_text(button_text, partial=True, timeout=15000)
        
            if not clicked:
                # Если не удалось кликнуть по тексту, пробуем по координатам
                coords = product_info.get("coordinates", {})
                if coords:
                    x = coords.get("x", 0) + coords.get("width", 0) / 2
                    y = coords.get("y", 0) + coords.get("height", 0) / 2
                    try:
                        await browser.page.mouse.click(x, y)
                        clicked = True
                        logger.info(f"Клик по координатам: ({x}, {y})")
                    except Exception as e:
                        logger.warning(f"Не удалось кликнуть по координатам: {e}")
        
            if not clicked:
                # Пробуем найти кнопку через селекторы
                button_selectors = [
                    'button:has-text("Buy")',
                    'button:has-text("Purchase")',
                    'button:has-text("Add to Cart")',
                    'button:has-text("Купить")',
                    'button[class*="buy"]',
                    'button[class*="purchase"]',
                    'a:has-text("Buy")',
                ]
            
                for selector in button_selectors:
                    try:
                        button = await browser.page.query_selector(selector)
                        if button and await button.is_visible():
                            await button.click()
                            clicked = True
                            logger.info(f"Кнопка найдена и нажата: {selector}")
                            break
                    except Exception:
                        continue
        
            if not clicked:
                await browser.take_screenshot(f"button_not_found_{session_id}.png")
                raise Exception(
                    f"Не удалось найти или нажать кнопку покупки для товара '{request.product_name}'. "
                    "Проверьте скриншот для диагностики."
                )
        
            # Ждём открытия формы оплаты или корзины
            await browser.human_like_delay(2000, 4000)
            await browser.take_screenshot(f"after_add_to_cart_{session_id}.png")
        
            # Проверяем, что товар добавлен в корзину или открыта форма оплаты
            current_url = browser.page.url
            page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")
        
            in_cart = (
                "cart" in current_url.lower() or
                "checkout" in current_url.lower() or
                "payment" in current_url.lower() or
                "cart" in page_text or
                "checkout" in page_text or
                "payment" in page_text
            )
        
            if not in_cart:
                # Возможно, открылось модальное окно или форма оплаты
                payment_selectors = [
                    'input[type="email"]',
                    'input[type="card"]',
                    'button:has-text("Pay")',
                    'button:has-text("Continue")',
                    '[class*="payment"]',
                    '[class*="checkout"]',
                ]
                has_payment_form = False
                for selector in payment_selectors:
                    try:
                        elem = await browser.page.query_selector(selector)
                        if elem and await elem.is_visible():
                            has_payment_form = True
                            logger.info(f"Обнаружена форма оплаты: {selector}")
                            break
                    except Exception:
                        continue
                if not has_payment_form:
                    logger.warning("Не удалось подтвердить добавление товара в корзину")
        
            added = in_cart or ('has_payment_form' in locals() and has_payment_form)
        
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
                    "price": product_info.get("price"),
                    "confidence": product_info.get("confidence"),
                    "description": product_info.get("description"),
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

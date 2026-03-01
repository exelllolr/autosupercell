"""API routes для авторизации в Supercell Store и привязки Google аккаунта."""

import asyncio
import random
import re
import time
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict
from loguru import logger
from app.config import settings
from app.core.browser_automation import BrowserAutomation
from app.core.email_code_reader import EmailCodeReader
from app.core.proxy_manager import proxy_manager


def _log_step(step: str, session_id: str, **kwargs) -> None:
    """Структурированный лог шага авторизации."""
    logger.info(
        "supercell_auth_step",
        step=step,
        session_id=session_id,
        timestamp=time.time(),
        **kwargs,
    )

router = APIRouter()


async def _accept_cookies(browser: BrowserAutomation) -> bool:
    """Принять cookies — быстрая проверка без долгих ожиданий."""
    if not browser.page:
        return False
    try:
        # Быстрая проверка через query_selector (не ждёт — просто смотрит есть ли сейчас)
        for selector in [
            'button:has-text("Accept All Cookies")',
            'button:has-text("Accept All")',
            'button:has-text("Accept Cookies")',
            'button:has-text("Accept")',
            '[role="button"]:has-text("Accept All Cookies")',
            'a:has-text("Accept All Cookies")',
        ]:
            try:
                el = await browser.page.query_selector(selector)
                if el and await el.is_visible():
                    await el.click(force=True)
                    logger.info(f"Cookies приняты: {selector}")
                    await browser.page.wait_for_timeout(500)
                    return True
            except Exception:
                continue

        return False
    except Exception as e:
        logger.debug(f"Ошибка при принятии cookies: {e}")
        return False


class SupercellLoginRequest(BaseModel):
    """Запрос на авторизацию в Supercell Store."""

    email: EmailStr
    email_password: Optional[str] = None  # Пароль для доступа к email (для получения кода)
    verification_code: Optional[str] = None  # Код верификации (если уже известен)
    use_existing_session: bool = False


class LinkGoogleAccountRequest(BaseModel):
    """Запрос на привязку Google аккаунта к Supercell."""

    supercell_email: EmailStr
    google_email: EmailStr
    google_password: Optional[str] = None



@router.post("/supercell/login")
async def supercell_login(request: SupercellLoginRequest):
    """
    Авторизация в Supercell Store.

    Args:
        request: Данные для авторизации в Supercell

    Returns:
        Информация о сессии
    """
    session_id = f"supercell_session_{request.email.replace('@', '_at_')}"
    # Retry при блокировке: до 3 попыток с новым IP Novada
    MAX_BLOCK_RETRIES = 3
    last_result = None

    # Фразы, при которых нужно retry с новым IP Novada
    BLOCK_PHRASES = [
        "unusual activity",
        "something went wrong",
        "try again later",
        "blocked your login",
        "please try again",
    ]

    last_error_msg = None

    for block_attempt in range(MAX_BLOCK_RETRIES):
        if block_attempt > 0:
            wait_sec = 5 + block_attempt * 5  # 10 сек, 15 сек — растущая пауза
            logger.info(
                f"Retry {block_attempt + 1}/{MAX_BLOCK_RETRIES} с новым браузером (новый fingerprint), "
                f"ждём {wait_sec} сек..."
            )
            await asyncio.sleep(wait_sec)

        # Полный перезапуск = новый экземпляр браузера и fingerprint каждую попытку
        browser = BrowserAutomation()
        browser.randomize_fingerprint()

        try:
            result = await _supercell_login_attempt(request, browser, session_id)

            # Если блокировка по result — retry с новым браузером
            msg = (result.get("message") or "").lower()
            if (
                result
                and not result.get("authenticated")
                and any(p in msg for p in BLOCK_PHRASES)
                and block_attempt < MAX_BLOCK_RETRIES - 1
            ):
                logger.warning(
                    f"Блокировка Supercell на попытке {block_attempt + 1} "
                    f"('{msg[:60]}...'), закрываем браузер и пробуем с новым..."
                )
                last_result = result
                try:
                    await browser.close()
                except Exception:
                    pass
                continue

            return result

        except HTTPException:
            raise
        except Exception as e:
            err_lower = str(e).lower()
            last_error_msg = str(e)
            logger.error(f"Ошибка авторизации в Supercell Store: {e}")

            # Retry если ошибка связана с блокировкой IP — закрываем браузер полностью
            if (
                any(p in err_lower for p in BLOCK_PHRASES)
                and block_attempt < MAX_BLOCK_RETRIES - 1
            ):
                logger.warning(
                    f"Блокировка через exception на попытке {block_attempt + 1}, "
                    f"закрываем браузер и пробуем с новым..."
                )
                try:
                    await browser.close()
                except Exception:
                    pass
                continue

            # Не блокировка — сразу 500
            try:
                await browser.close()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail={"error": str(e)})

    # Все попытки исчерпаны — сбрасываем failed_proxies для следующего цикла
    proxy_manager.reset_failed_proxies()
    if last_result:
        return last_result
    raise HTTPException(
        status_code=500,
        detail={"error": last_error_msg or "Все попытки авторизации исчерпаны (блокировка IP Novada)"}
    )


async def _supercell_login_attempt(request: SupercellLoginRequest, browser: "BrowserAutomation", session_id: str):
    """Одна попытка авторизации в Supercell Store."""
    try:
        logger.info(
            f"Начало авторизации в Supercell Store для {request.email}. "
            f"verification_code={'***' + (request.verification_code or '')[-2:] if request.verification_code else None}, "
            f"email_password={'***' if request.email_password else None}"
        )

        store_url = "https://store.supercell.com"
        nav_timeout = 120000
        max_proxy_retries = 3
        store_loaded = False

        for proxy_attempt in range(max_proxy_retries):
            if proxy_attempt > 0:
                browser = BrowserAutomation()
                await browser.start()
            else:
                await browser.start()

            # Прогрев: сначала supercell.com, потом store — естественная цепочка для антибота
            if getattr(settings, "BROWSER_WARMUP_VISIT_SUPERCELL", True):
                try:
                    await browser.page.goto("https://www.supercell.com", wait_until="domcontentloaded", timeout=15000)
                    await browser.human_like_delay(2000, 4000)
                    logger.info("Прогрев: посещение supercell.com")
                except Exception as e:
                    logger.debug("Прогрев supercell.com пропущен: %s", e)

            logger.info("Переход на главную страницу Supercell Store...")
            load_state_timeout = 90000
            for attempt in range(2):
                try:
                    await browser.page.goto(
                        store_url, wait_until="commit", timeout=nav_timeout
                    )
                    await browser.page.wait_for_load_state("domcontentloaded", timeout=load_state_timeout)
                    store_loaded = True
                    break
                except Exception as nav_err:
                    err_lower = str(nav_err).lower()
                    is_proxy_error = (
                        "err_empty_response" in err_lower
                        or "net::err_" in err_lower
                        or "err_connection_reset" in err_lower
                    )
                    is_timeout = "timeout" in err_lower or "timed_out" in err_lower or "exceeded" in err_lower
                    if is_timeout and attempt == 0:
                        logger.warning(f"Таймаут загрузки store (попытка 1/2). Повтор через 5 сек...")
                        await asyncio.sleep(5)
                        continue
                    if is_proxy_error and proxy_attempt < max_proxy_retries - 1:
                        if getattr(browser, "current_proxy", None):
                            proxy_manager.mark_proxy_failed(browser.current_proxy)
                        try:
                            await browser.close()
                        except Exception:
                            pass
                        logger.warning(
                            f"Прокси не загрузил store: {nav_err}. "
                            f"Пробуем другой прокси ({proxy_attempt + 2}/{max_proxy_retries})..."
                        )
                        await asyncio.sleep(2)
                        break  # выходим из inner loop, proxy_attempt увеличится
                    raise Exception(
                        f"Не удалось загрузить {store_url}: {nav_err}. "
                        "Возможные причины:\n"
                        "1. Прокси не отвечает или слишком медленный — проверьте proxies.txt\n"
                        "2. Временно отключите прокси: PROXY_ENABLED=false в .env\n"
                        "3. Проверьте прокси: python examples/test_webshare_proxy.py"
                    )
            if store_loaded:
                break

        # Принимаем cookies, если есть баннер
        await _accept_cookies(browser)
        await browser.human_like_delay(1000, 2000)

        # Долгое «чтение» страницы перед кликом Log in (5–8 сек)
        await browser.simulate_reading_page(6)
        await browser.take_screenshot(f"supercell_store_start_{session_id}.png")
        
        # Проверяем на наличие блокировки на главной странице
        page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")
        if "blocked" in page_text or "unusual activity" in page_text:
            logger.warning("Обнаружена блокировка на главной странице Supercell")
            await browser.take_screenshot(f"supercell_blocked_detected_{session_id}.png")
            raise Exception(
                "Supercell заблокировал доступ на главной странице. "
                "Возможные причины:\n"
                "1. IP адрес в черном списке\n"
                "2. Обнаружена автоматизация\n"
                "3. Требуется резидентный прокси\n"
                "Рекомендации:\n"
                "- Используйте резидентный прокси (Novada Residential)\n"
                "- Попробуйте через несколько часов\n"
                "- Используйте другой прокси"
            )

        # Ищем кнопку входа/логина
        login_selectors = [
            'a:has-text("Log in")',
            'a:has-text("Sign in")',
            'button:has-text("Log in")',
            'button:has-text("Sign in")',
            '[href*="login"]',
            '[href*="signin"]',
            '.login-button',
            '#login-button',
            'text=/log.?in/i',  # Регулярное выражение для "log in" или "login"
        ]

        login_clicked = False
        for selector in login_selectors:
            try:
                element = await browser.page.query_selector(selector)
                if element:
                    # Проверяем видимость элемента
                    is_visible = await element.is_visible()
                    if is_visible:
                        await element.click()
                        login_clicked = True
                        logger.info(f"Кнопка входа найдена: {selector}")
                        break
            except Exception as e:
                logger.debug(f"Селектор {selector} не найден: {e}")
                continue

        if not login_clicked:
            # Пробуем найти через текст на странице
            try:
                await browser.page.click('text=Log in', timeout=5000)
                login_clicked = True
            except Exception:
                # Пробуем через локализацию
                try:
                    await browser.page.click('text=/войти|вход|log.?in/i', timeout=5000)
                    login_clicked = True
                except Exception:
                    pass

        if login_clicked:
            await browser.take_screenshot(f"supercell_login_clicked_{session_id}.png")
            # Ждём естественного редиректа после клика — НЕ делаем принудительный goto
            logger.info("Переход на страницу авторизации Supercell ID (ждём редиректа)...")
            try:
                # Ждём когда URL изменится на accounts.supercell.com или id.supercell.com
                await browser.page.wait_for_url(
                    lambda url: "accounts.supercell.com" in url or "id.supercell.com" in url,
                    timeout=15000,
                )
                logger.info(f"Редирект выполнен: {browser.page.url}")
            except Exception:
                # Если редирект не произошёл — делаем прямой переход
                logger.warning("Редирект не произошёл, переходим напрямую на accounts.supercell.com/login")
                try:
                    await browser.page.goto(
                        "https://accounts.supercell.com/login",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                except Exception as e:
                    logger.debug(f"Ошибка перехода: {e}")
        else:
            logger.warning("Кнопка входа не найдена, переходим напрямую")
            try:
                await browser.page.goto(
                    "https://accounts.supercell.com/login",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
            except Exception as e:
                logger.debug(f"Ошибка перехода: {e}")

        await browser.page.wait_for_load_state("domcontentloaded", timeout=15000)
        logger.info(f"Страница загружена: {browser.page.url}")

        # Принимаем cookies если появились
        await browser.human_like_delay(800, 1500)
        cookies_accepted = await _accept_cookies(browser)
        if cookies_accepted:
            logger.info("Cookies приняты на странице логина")
        await browser.human_like_delay(500, 1000)

        # Если попали на id.supercell.com — нажимаем кнопку входа
        current_url = browser.page.url
        if "id.supercell.com" in current_url and "accounts.supercell.com" not in current_url:
            for sel in ['button:has-text("LOG IN")', 'button:has-text("Log in")', 'a:has-text("Log in")']:
                try:
                    el = await browser.page.wait_for_selector(sel, timeout=4000)
                    if el and await el.is_visible():
                        await el.click()
                        logger.info(f"Кнопка входа на id.supercell.com нажата: {sel}")
                        await browser.human_like_delay(2000, 3000)
                        await _accept_cookies(browser)
                        break
                except Exception:
                    continue
        else:
            logger.info(f"На странице логина: {current_url}")

        # Задержка перед LOG IN с рандомизацией ±30% (из config)
        base_delay_before = getattr(settings, "SUPERCELL_LOGIN_DELAY_BEFORE_SUBMIT", 15)
        delay_before_sec = base_delay_before * random.uniform(0.7, 1.3)
        logger.info(f"Ожидание перед LOG IN: {delay_before_sec:.1f} сек (база {base_delay_before} ±30%)")
        await asyncio.sleep(delay_before_sec)
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

        # Если Supercell ID показал «Something went wrong» — IP заблокирован, нужен новый IP (retry)
        page_text_pre = (await browser.page.evaluate("() => document.body.innerText")).lower()
        if "something went wrong" in page_text_pre or "try again later" in page_text_pre:
            logger.warning("Обнаружено «Something went wrong» — IP заблокирован Supercell, нужен новый IP")
            await browser.take_screenshot(f"supercell_something_went_wrong_{session_id}.png")
            raise Exception(
                "Supercell ID вернул «Something went wrong» — IP заблокирован. "
                "Автоматически пробуем новый IP Novada..."
            )

        # Ищем поле email — первый селектор ждём 30 сек (SPA может грузиться долго)
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

        await browser.human_like_delay(500, 1000)

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

        # Перед вводом email: если на странице уже «blocked»/«unusual activity» — нужен новый IP (retry)
        page_text_before_fill = (await browser.page.evaluate("() => document.body.innerText")).lower()
        if (
            "we have blocked your login request" in page_text_before_fill
            or "blocked your login request" in page_text_before_fill
            or "unusual activity" in page_text_before_fill
        ):
            await browser.take_screenshot(f"supercell_blocked_before_fill_{session_id}.png")
            raise Exception(
                "Supercell заблокировал вход (unusual activity) — IP заблокирован. "
                "Автоматически пробуем новый IP Novada..."
            )

        if not email_input:
            await browser.take_screenshot(f"supercell_no_email_field_{session_id}.png")
            page_html = await browser.page.content()
            logger.error(f"HTML страницы (первые 2000 символов): {page_html[:2000]}")
            page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")

            if "something went wrong" in page_text or "try again later" in page_text:
                raise Exception(
                    "Supercell ID вернул ошибку «Something went wrong. Please try again later.» — форма входа не загрузилась. "
                    "Попробуйте через 5–10 минут, с другим прокси или без прокси (PROXY_ENABLED=false)."
                )
            if "blocked" in page_text or "unusual activity" in page_text:
                raise Exception(
                    "Supercell заблокировал вход из-за обнаружения автоматизации. "
                    "Рекомендации: другой прокси/IP, увеличить задержки, попробовать позже."
                )
            raise Exception(
                "Поле email не найдено на странице входа Supercell. "
                "Возможные причины: страница не загрузилась (чёрный экран), ошибка Supercell ID или блокировка. "
                "Проверьте скриншот в screenshots/ и попробуйте позже или с другим прокси."
            )

        # Короткая пауза перед вводом — как человек который увидел форму
        await browser.human_like_delay(800, 1500)

        # Одно движение мыши к полю email (естественное поведение)
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

        # Вводим email медленно (реальные нажатия клавиш) — reCAPTCHA оценивает скорость ввода
        await browser.human_like_type(found_email_selector, request.email, delay_between_chars=130)
        await browser.human_like_delay(800, 1500)
        
        # Проверяем, что email введен правильно
        entered_email = await browser.page.input_value(found_email_selector)
        if entered_email != request.email:
            # Повторный ввод через keyboard (без fill())
            await browser.page.keyboard.press("Control+a")
            await browser.page.wait_for_timeout(random.randint(50, 150))
            await browser.page.keyboard.press("Delete")
            await browser.human_like_delay(200, 400)
            await browser.human_like_type(found_email_selector, request.email, delay_between_chars=130)
            await browser.human_like_delay(500, 1000)
        
        await browser.take_screenshot(f"supercell_email_filled_{session_id}.png")
        _log_step(
            "email_entered",
            session_id,
            proxy=browser.current_proxy.get("server") if browser.current_proxy else None,
            user_agent=(browser.current_user_agent or "")[:50],
        )

        # Перед нажатием LOG IN: если за время ввода появилось «blocked»/«unusual activity» — не жмём
        page_text_before_click = (await browser.page.evaluate("() => document.body.innerText")).lower()
        if "we have blocked your login request" in page_text_before_click or "blocked your login request" in page_text_before_click or "unusual activity" in page_text_before_click:
            await browser.take_screenshot(f"supercell_blocked_before_login_click_{session_id}.png")
            raise Exception(
                "Supercell заблокировал вход (unusual activity) на шаге ввода email. "
                "Отключите прокси (PROXY_ENABLED=false) или используйте резидентный прокси; попробуйте позже."
            )

        # Сначала ищем кнопку именно внутри формы с email (чтобы не нажать "Log in" в шапке)
        form_scoped_selectors = [
            f"form:has({found_email_selector}) button[type='submit']",
            f"form:has({found_email_selector}) button:has-text('LOG IN')",
            f"form:has({found_email_selector}) button:has-text('Log in')",
            f"form:has({found_email_selector}) button:has-text('Next')",
            f"form:has({found_email_selector}) button:has-text('Continue')",
            f"form:has({found_email_selector}) button",
        ]
        # Затем общие селекторы кнопки перехода к вводу кода
        continue_selectors = form_scoped_selectors + [
            'button:has-text("Send code")',
            'button:has-text("Get code")',
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button:has-text("Далее")',
            'button:has-text("Продолжить")',
            'button:has-text("Log in")',
            'button:has-text("Sign in")',
            'button[type="submit"]',
            'input[type="submit"]',
            'button[aria-label*="next" i]',
            'button[aria-label*="continue" i]',
            'button[aria-label*="send" i]',
            '[role="button"]:has-text("Next")',
            '[role="button"]:has-text("Continue")',
            'a:has-text("Next")',
            'a:has-text("Continue")',
        ]

        # Опционально: решаем reCAPTCHA через 2Captcha и подставляем токен
        captcha_token = None
        if getattr(settings, "CAPTCHA_2CAPTCHA_API_KEY", ""):
            from app.core.recaptcha_solver import solve_recaptcha_enterprise
            captcha_token = await solve_recaptcha_enterprise(
                api_key=settings.CAPTCHA_2CAPTCHA_API_KEY,
                page_url=browser.page.url or "https://accounts.supercell.com/login",
                timeout=120,
            )
            logger.info("reCAPTCHA токен получен: {}".format(captcha_token is not None))
            if captcha_token:
                # Подменяем grecaptcha.enterprise.execute — при клике LOG IN сайт получит наш токен
                import json
                token_js = json.dumps(captcha_token)
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
                # Добавляем скрытое поле в форму (на случай если отправка идёт через form submit)
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
            else:
                logger.warning("2Captcha не вернул токен — ожидание 60 сек на ручной ввод reCAPTCHA")
                try:
                    await browser.page.wait_for_timeout(60000)  # 60 сек fallback на ручное решение
                    await browser.take_screenshot(f"supercell_recaptcha_manual_{session_id}.png")
                except Exception:
                    pass
        else:
            logger.debug("CAPTCHA_2CAPTCHA_API_KEY не задан — reCAPTCHA не решаем через сервис")

        # Проверка: если на странице есть reCAPTCHA, но токена нет — не отправлять форму (избежать блокировки)
        has_recaptcha = await browser.page.evaluate(
            """() => typeof window.grecaptcha !== 'undefined' && (window.grecaptcha && (window.grecaptcha.enterprise || window.grecaptcha))"""
        )
        skip_login_click = bool(has_recaptcha and not captcha_token)
        if skip_login_click:
            logger.warning(
                "Обнаружен reCAPTCHA на странице, токен не получен — не отправляем форму. "
                "Задайте CAPTCHA_2CAPTCHA_API_KEY или решите капчу вручную."
            )
            await browser.human_like_delay(1000, 2000)

        await browser.human_like_delay(1000, 2000)

        # Ищем кнопку LOG IN и кликаем реальным движением мыши (пропускаем, если reCAPTCHA без токена)
        continue_clicked = False
        if not skip_login_click:
            # Сначала пробуем через bounding_box — самый надёжный способ
            for selector in continue_selectors:
                try:
                    element = await browser.page.wait_for_selector(selector, timeout=3000)
                    if not element or not await element.is_visible():
                        continue
                    box = await element.bounding_box()
                    if not box:
                        continue
                    # Целевые координаты — немного смещаем от центра
                    target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
                    target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
                    # Плавное движение мыши с ускорением (Bezier-подобная кривая)
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
                    # Движение по кривой (25–40 шагов, микро-дрожания), пауза 300–800 ms перед кликом
                    mid_x = (start_x + target_x) / 2 + random.uniform(-20, 20)
                    mid_y = (start_y + target_y) / 2 + random.uniform(-15, 15)
                    steps = random.randint(25, 40)
                    for i in range(steps):
                        t = (i + 1) / steps
                        bx = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * mid_x + t ** 2 * target_x
                        by = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * mid_y + t ** 2 * target_y
                        jitter_x = random.uniform(-2, 2)
                        jitter_y = random.uniform(-2, 2)
                        await browser.page.mouse.move(bx + jitter_x, by + jitter_y)
                        await browser.page.wait_for_timeout(random.randint(8, 20))
                    await browser.page.wait_for_timeout(random.randint(300, 800))
                    await browser.page.mouse.click(target_x, target_y, delay=random.randint(60, 130))
                    continue_clicked = True
                    logger.info(f"Кнопка LOG IN нажата (mouse.click по bounding_box): {selector}")
                    break
                except Exception as e:
                    logger.debug(f"Селектор {selector}: {e}")
                    continue

            if not continue_clicked:
                logger.warning("Кнопка не найдена через селекторы, пробуем Tab+Enter")
                try:
                    await browser.page.keyboard.press("Tab")
                    await browser.page.wait_for_timeout(random.randint(150, 300))
                    await browser.page.keyboard.press("Enter")
                    continue_clicked = True
                    logger.info("Кнопка нажата через Tab+Enter")
                except Exception as e:
                    logger.debug(f"Tab+Enter не сработал: {e}")

        # Ждём ответа от сервера после нажатия LOG IN
        await browser.human_like_delay(1000, 2000)
        await _accept_cookies(browser)

        logger.info("Ожидание формы кода верификации...")
        await browser.human_like_delay(1500, 2500)
        await browser.take_screenshot(f"supercell_after_email_{session_id}.png")
        
        # Дожидаемся перехода к шагу ввода кода (страница /verify или изменение контента на /login)
        verify_reached = False
        is_blocked = False

        # Сразу после клика LOG IN: если страница уже показывает «blocked»/«unusual activity» — не ждём 3 мин
        page_text_after_click = (await browser.page.evaluate("() => document.body.innerText")).lower()
        if "we have blocked your login request" in page_text_after_click or "blocked your login request" in page_text_after_click or "unusual activity" in page_text_after_click:
            is_blocked = True
            logger.warning("Обнаружено «blocked»/«unusual activity» сразу после нажатия LOG IN")
        
        # Проверяем URL на /verify (только если ещё не помечены как blocked)
        if not is_blocked:
            try:
                await browser.page.wait_for_url(
                    lambda url: "/verify" in url,
                    timeout=10000,
                )
                verify_reached = True
                logger.info("Редирект на /verify выполнен")
            except Exception:
                logger.debug("Редирект на /verify не произошёл, проверяем элементы на странице")
        
        # Если редирект не произошёл и не blocked — ждём OTP поле с периодическим принятием куки
        if not verify_reached and not is_blocked:
            code_selectors = [
                'input[type="text"][maxlength="6"]',
                'input[type="text"][maxlength="7"]',
                'input[type="tel"]',
                'input[autocomplete="one-time-code"]',
                'input[inputmode="numeric"]',
                'input[placeholder*="123" i]',
            ]
            
            # Периодически принимаем куки пока ждём OTP поле (каждые 15 сек)
            async def _wait_for_otp_with_cookie_accept(timeout_total_ms: int = 180000):
                nonlocal verify_reached, is_blocked
                start_time = asyncio.get_event_loop().time()
                cookie_check_interval = 15.0  # сек
                last_cookie_check = 0.0
                while True:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed * 1000 >= timeout_total_ms:
                        break
                    # Периодически принимаем куки
                    if elapsed - last_cookie_check >= cookie_check_interval:
                        await _accept_cookies(browser)
                        last_cookie_check = elapsed
                    # Проверяем URL
                    if "/verify" in browser.page.url:
                        verify_reached = True
                        logger.info("URL переключился на /verify")
                        return
                    # Проверяем наличие OTP поля
                    for selector in code_selectors:
                        try:
                            el = await browser.page.query_selector(selector)
                            if el:
                                attr_type = await el.get_attribute("type") or ""
                                attr_ph = await el.get_attribute("placeholder") or ""
                                if attr_type.lower() != "email" and "email" not in attr_ph.lower():
                                    verify_reached = True
                                    logger.info(f"OTP поле найдено: {selector}")
                                    return
                        except Exception:
                            pass
                    # Проверяем текстовые индикаторы verify шага
                    try:
                        page_content = await browser.page.evaluate("() => document.body.innerText")
                        pc_lower = page_content.lower()
                        if "we have blocked your login request" in pc_lower or "blocked your login request" in pc_lower or "unusual activity" in pc_lower:
                            is_blocked = True
                            logger.warning("В цикле ожидания обнаружено «blocked»/«unusual activity»")
                            return
                        verify_texts = ["Almost there", "Didn't receive", "GO BACK", "Enter the code", "Verify"]
                        if any(t.lower() in pc_lower for t in verify_texts):
                            verify_reached = True
                            logger.info("Текст verify шага обнаружен на странице")
                            return
                    except Exception:
                        pass
                    await browser.page.wait_for_timeout(2000)

            await _wait_for_otp_with_cookie_accept(timeout_total_ms=180000)

            # Запасной путь через wait_for_selector если выше не нашли
            if not verify_reached:
                for i, selector in enumerate(code_selectors):
                    timeout_ms = 30000 if i == 0 else 10000
                    try:
                        code_input = await browser.page.wait_for_selector(selector, timeout=timeout_ms)
                        if code_input:
                            input_type = await code_input.get_attribute("type") or ""
                            placeholder = await code_input.get_attribute("placeholder") or ""
                            if input_type.lower() != "email" and "email" not in placeholder.lower():
                                verify_reached = True
                                logger.info(f"Поле OTP кода обнаружено: {selector}")
                                break
                    except Exception:
                        continue
        
        # Проверяем на блокировку ТОЛЬКО если не удалось дойти до шага Verify (is_blocked мог быть уже установлен выше)
        if not verify_reached:
            await browser.take_screenshot(f"supercell_verify_not_reached_{session_id}.png")
            current_url = browser.page.url
            block_error_text = None
            
            # Ищем конкретные элементы ошибки блокировки (красные/оранжевые сообщения)
            try:
                # Более специфичные селекторы для сообщений об ошибке блокировки
                error_selectors = [
                    '[role="alert"]',
                    '.error',
                    '.alert-danger',
                    '[class*="error"]',
                    '[class*="blocked"]',
                    '[class*="alert"]',
                ]
                
                block_indicators = [
                    "we have blocked your login request",
                    "blocked your login request",
                    "unusual activity",
                ]
                
                for selector in error_selectors:
                    try:
                        error_elements = await browser.page.query_selector_all(selector)
                        for elem in error_elements:
                            try:
                                text = (await elem.inner_text()).lower()
                                # Проверяем, что это действительно сообщение об ошибке блокировки
                                if any(ind in text for ind in block_indicators):
                                    # Дополнительная проверка: элемент должен быть видимым и содержать ошибку
                                    is_visible = await elem.is_visible()
                                    if is_visible:
                                        is_blocked = True
                                        block_error_text = text[:200]
                                        logger.warning(f"Обнаружено сообщение о блокировке: {text[:100]}")
                                        break
                            except Exception:
                                continue
                        if is_blocked:
                            break
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Ошибка при проверке блокировки: {e}")
            # Дополнительно: по тексту всей страницы (на случай если сообщение не в [role=alert]/.error)
            if not is_blocked:
                try:
                    pt = (await browser.page.evaluate("() => document.body.innerText")).lower()
                    if "we have blocked your login request" in pt or "blocked your login request" in pt or "unusual activity" in pt:
                        is_blocked = True
                        block_error_text = pt[:200]
                except Exception:
                    pass
            
            # Если не нашли через элементы, проверяем URL и наличие спиннера/загрузки
            if not is_blocked:
                # Проверяем, не зависла ли страница на загрузке (возможно, reCAPTCHA или антибот)
                try:
                    # Ищем спиннеры загрузки
                    loading_selectors = [
                        '[class*="spinner"]',
                        '[class*="loading"]',
                        '[class*="loader"]',
                        '[aria-busy="true"]',
                    ]
                    has_loading = False
                    for selector in loading_selectors:
                        try:
                            loading_elem = await browser.page.query_selector(selector)
                            if loading_elem and await loading_elem.is_visible():
                                has_loading = True
                                logger.debug(f"Обнаружен индикатор загрузки: {selector}")
                                break
                        except Exception:
                            continue
                    
                    # Если есть загрузка, ждём ещё немного
                    if has_loading:
                        logger.info("Обнаружен индикатор загрузки, ожидаем завершения...")
                        await browser.human_like_delay(5000, 8000)
                        # Повторно проверяем поле кода
                        for selector in ['input[type="tel"]', 'input[autocomplete="one-time-code"]', 'input[inputmode="numeric"]']:
                            try:
                                code_input = await browser.page.wait_for_selector(selector, timeout=10000)
                                if code_input:
                                    verify_reached = True
                                    logger.info(f"Поле OTP кода появилось после ожидания: {selector}")
                                    break
                            except Exception:
                                continue
                except Exception:
                    pass
            
            # Если форма кода появилась после ожидания, продолжаем работу
            if verify_reached:
                logger.info("Форма кода верификации обнаружена, продолжаем процесс авторизации")
            elif is_blocked:
                # Это ожидаемая ситуация (антибот), не 500.
                screenshot_path = await browser.take_screenshot(
                    f"supercell_login_blocked_{session_id}.png"
                )
                html_path = None
                try:
                    from pathlib import Path

                    tmp_dir = Path("tmp")
                    tmp_dir.mkdir(exist_ok=True)
                    html_path = tmp_dir / f"supercell_blocked_after_email_{session_id}.html"
                    html_path.write_text(await browser.page.content(), encoding="utf-8")
                except Exception:
                    pass

                _log_step("blocked_after_email", session_id, debug_html=str(html_path) if html_path else None)
                result = {
                    "success": False,
                    "session_id": session_id,
                    "email": request.email,
                    "authenticated": False,
                    "screenshot": str(screenshot_path),
                    "url": browser.page.url if browser.page else None,
                    "message": (
                        "Supercell заблокировал вход после отправки email (unusual activity). "
                        "Это не ошибка кода/таймаутов — сайт не даёт перейти к /verify.\n"
                        "Возможные причины:\n"
                        "1. IP/подсеть в черных списках (часто у datacenter прокси)\n"
                        "2. Детект автоматизации / слишком частые попытки\n"
                        "3. Требуется reCAPTCHA/доп. проверка\n"
                        "Что делать:\n"
                        "- Тестируйте локально через VPN (как в ручном браузере)\n"
                        "- Или используйте резидентный прокси (Bright Data/Novada Residential, US)\n"
                        "- Увеличьте паузы между попытками и не дергайте логин многократно подряд"
                    ),
                }
                if html_path:
                    result["debug_html"] = str(html_path)

                # Закрываем браузер, чтобы сохранить видео
                try:
                    video_path = await browser.close()
                    if video_path:
                        result["video"] = video_path
                except Exception:
                    pass

                return result
            else:
                # Не блокировка, но и форма кода не появилась - возможно, страница еще загружается
                # или требуется больше времени
                html_path = None
                try:
                    from pathlib import Path

                    tmp_dir = Path("tmp")
                    tmp_dir.mkdir(exist_ok=True)
                    html_path = tmp_dir / f"supercell_verify_not_reached_{session_id}.html"
                    html_path.write_text(await browser.page.content(), encoding="utf-8")
                except Exception:
                    pass

                screenshot_path = await browser.take_screenshot(
                    f"supercell_verify_not_reached_{session_id}.png"
                )
                result = {
                    "success": False,
                    "session_id": session_id,
                    "email": request.email,
                    "authenticated": False,
                    "screenshot": str(screenshot_path),
                    "url": browser.page.url if browser.page else None,
                    "message": (
                        "Не удалось перейти к окну ввода кода (verify). "
                        "Возможные причины:\n"
                        "1. Страница еще загружается (попробуйте подождать)\n"
                        "2. reCAPTCHA/антибот зависают на отправке кода\n"
                        "3. Плохой IP/прокси\n"
                        "4. Требуется дополнительная проверка"
                    ),
                }
                if html_path:
                    result["debug_html"] = str(html_path)

                # Закрываем браузер, чтобы сохранить видео
                try:
                    video_path = await browser.close()
                    if video_path:
                        result["video"] = video_path
                except Exception:
                    pass

                return result

        # Режим ручного ввода: если код не передан и нет доступа к email — ждём 2 минуты, пока пользователь введёт код вручную
        verification_code = request.verification_code
        code_entered_manually = False

        if not verification_code and not request.email_password:
            logger.info("Ожидание до 2 минут — введите код верификации вручную в браузере.")
            manual_wait_seconds = 120
            deadline = asyncio.get_event_loop().time() + manual_wait_seconds
            code_input_selectors = [
                'input[type="tel"]',
                'input[autocomplete="one-time-code"]',
                'input[inputmode="numeric"]',
                'input[placeholder*="123" i]',
                'input[type="text"][maxlength="6"]',
                'input[type="text"][maxlength="7"]',
            ]
            continue_clicked = False
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
                            continue_clicked = True
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
                                    continue_clicked = True
                                    code_entered_manually = True
                                break
                    if continue_clicked:
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)
            if not code_entered_manually:
                await browser.take_screenshot(f"supercell_manual_code_timeout_{session_id}.png")
                raise Exception(
                    "Истекло 2 минуты ожидания ручного ввода кода. "
                    "Введите код верификации в браузере в течение 2 минут или передайте verification_code / email_password."
                )

        if not code_entered_manually:
            # Нормализуем код верификации (убираем пробелы и дефисы)
            if verification_code:
                verification_code = verification_code.replace(" ", "").replace("-", "").strip()
                if len(verification_code) != 6 or not verification_code.isdigit():
                    raise Exception(
                        f"Неверный формат кода верификации. "
                        f"Код должен быть 6 цифр, получено: '{request.verification_code}'"
                    )
        
            # Если код не передан, пытаемся получить из email (если есть пароль)
            if not verification_code:
                if request.email_password:
                    logger.info("Ожидание кода верификации из email...")
                    try:
                        email_reader = EmailCodeReader(request.email, request.email_password)
                        verification_code = email_reader.get_supercell_code(timeout=120)
                        
                        if not verification_code:
                            await browser.take_screenshot(f"supercell_code_not_received_{session_id}.png")
                            raise Exception(
                                "Код верификации не получен из email. "
                                "Возможные причины:\n"
                                "1. Письмо от Supercell еще не пришло (подождите 1-2 минуты)\n"
                                "2. Проверьте папку 'Спам' в почте\n"
                                "3. Неверные учетные данные для доступа к email\n"
                                "4. Для Gmail с включенной 2FA требуется App Password\n"
                                "Проверьте правильность email и пароля."
                            )
                    except Exception as e:
                        await browser.take_screenshot(f"supercell_email_error_{session_id}.png")
                        raise Exception(str(e))
                else:
                    await browser.take_screenshot(f"supercell_no_code_{session_id}.png")
                    raise Exception(
                        "Код верификации не предоставлен. "
                        "Введите код верификации из письма Supercell в поле 'verification_code' или "
                        "предоставьте 'email_password' для автоматического получения кода из email."
                    )

            if verification_code:
                logger.info(f"Используем код верификации: {verification_code[:2]}**")
            
            # Ищем поле для ввода кода.
            # ВАЖНО: если verify_reached уже True (текст найден в цикле выше) — не ждём 3 мин,
            # а сразу ищем поле с коротким таймаутом.
            code_selectors = [
                'input[type="text"][maxlength="6"]',
                'input[type="text"][maxlength="7"]',
                'input[type="tel"]',
                'input[autocomplete="one-time-code"]',
                'input[inputmode="numeric"]',
                'input[placeholder*="123" i]',
                'input[type="number"]',
                'input[name*="code"]',
                'input[name*="verification"]',
                'input[name*="otp"]',
                'input[id*="code"]',
                'input[id*="verification"]',
                'input[id*="otp"]',
                'input[placeholder*="code" i]',
            ]

            code_input = None
            found_code_selector = None

            # Если verify_reached — страница уже показывает шаг Verify, поле должно быть здесь
            if verify_reached:
                logger.info("Verify шаг уже обнаружен, ищем поле кода (таймаут 30 сек)...")
                for selector in code_selectors:
                    try:
                        el = await browser.page.wait_for_selector(selector, timeout=30000)
                        if el:
                            input_type = (await el.get_attribute("type")) or ""
                            ph = (await el.get_attribute("placeholder")) or ""
                            if input_type.lower() != "email" and "email" not in ph.lower():
                                code_input = el
                                found_code_selector = selector
                                logger.info(f"Найдено поле кода: {selector}")
                                break
                    except Exception:
                        continue
            else:
                # verify_reached=False: ждём появления шага Verify и поля кода
                logger.info("Ожидание шага Verify на странице (Almost there / Go back / Didn't receive)...")
                step_visible = False
                for step_text in ["almost there", "didn't receive the code", "go back", "enter the code", "check your email"]:
                    try:
                        await browser.page.get_by_text(re.compile(step_text, re.I)).first.wait_for(state="visible", timeout=20000)
                        step_visible = True
                        logger.info(f"Шаг ввода кода обнаружен по тексту: {step_text}")
                        break
                    except Exception:
                        continue
                if not step_visible:
                    logger.info("Шаг Verify не обнаружен по тексту, ищем поле кода напрямую...")
                    await browser.human_like_delay(2000, 3000)

                logger.info("Ожидание поля ввода кода (до 3 минут)...")
                for i, selector in enumerate(code_selectors):
                    timeout_ms = 180000 if i == 0 else 30000
                    try:
                        el = await browser.page.wait_for_selector(selector, timeout=timeout_ms)
                        if el:
                            input_type = (await el.get_attribute("type")) or ""
                            ph = (await el.get_attribute("placeholder")) or ""
                            if input_type.lower() != "email" and "email" not in ph.lower() and selector != found_email_selector:
                                code_input = el
                                found_code_selector = selector
                                logger.info(f"Найдено поле кода: {selector}")
                                break
                    except Exception:
                        continue
            
            # Если не нашли в main frame — ищем во всех iframe (увеличен таймаут)
            if not code_input and browser.page.frames:
                for frame in browser.page.frames:
                    if frame == browser.page.main_frame:
                        continue
                    for selector in code_selectors[:8]:
                        try:
                            # Увеличен таймаут для iframe до 20 сек (через прокси может быть медленно)
                            code_input = await frame.wait_for_selector(selector, timeout=20000)
                            if code_input:
                                found_code_selector = selector
                                logger.info(f"Поле кода найдено в iframe: {selector}")
                                break
                        except Exception:
                            continue
                    if code_input:
                        break
            
            # Проверяем: может быть 6 отдельных полей для цифр (как на многих формах OTP)
            six_digit_inputs = None
            if not code_input:
                try:
                    inputs = await browser.page.query_selector_all('input[type="text"][maxlength="1"], input[type="tel"][maxlength="1"], input[inputmode="numeric"]')
                    if len(inputs) >= 6:
                        six_digit_inputs = inputs[:6]
                        logger.info("Найдено 6 отдельных полей для кода")
                except Exception:
                    pass

            if code_input:
                await browser.human_like_delay(300, 600)
                await code_input.fill("")
                await code_input.type(verification_code, delay=80)
                await browser.human_like_delay(500, 1000)
                await browser.take_screenshot(f"supercell_code_filled_{session_id}.png")
                # Пробуем отправить форму: Enter (часто срабатывает для OTP) и клик по кнопке
                verify_clicked = False
                await code_input.focus()
                await browser.page.keyboard.press("Enter")
                await browser.human_like_delay(1500, 2500)
                try:
                    current_url = browser.page.url
                    if "store.supercell.com" in current_url and "login" not in current_url.lower():
                        verify_clicked = True
                        logger.info("Отправка по Enter — редирект на store выполнен")
                except Exception:
                    pass
                # Supercell часто требует клик по CONTINUE (и кнопка может быть aria-disabled)
                if not verify_clicked:
                    try:
                        # ВАЖНО: не используем wait_for_function — на accounts.supercell.com CSP блокирует unsafe-eval.
                        # Вместо этого поллим состояние кнопки через Playwright API.
                        btn_loc = browser.page.get_by_role(
                            "button", name=re.compile(r"continue", re.I)
                        )
                        if await btn_loc.count() > 0:
                            btn = btn_loc.first
                            deadline = asyncio.get_event_loop().time() + 120.0
                            while asyncio.get_event_loop().time() < deadline:
                                try:
                                    aria = (await btn.get_attribute("aria-disabled")) or ""
                                    aria_disabled = aria.strip().lower() == "true"
                                    disabled = False
                                    try:
                                        disabled = await btn.is_disabled()
                                    except Exception:
                                        disabled = False
                                    if not disabled and not aria_disabled:
                                        logger.info("Кнопка CONTINUE стала активной (enabled)")
                                        break
                                except Exception:
                                    pass
                                await browser.page.wait_for_timeout(500)
                    except Exception:
                        logger.debug("Не дождались enabled кнопки CONTINUE (возможно, уже активна/другой текст)")
                if not verify_clicked:
                    for sel in (
                        'button:has-text("VERIFY")', 'button:has-text("Verify")', 'button:has-text("Confirm")',
                        'button:has-text("Continue")', 'button:has-text("CONTINUE")', 'button:has-text("Submit")', 'button[type="submit"]',
                        '[role="button"]:has-text("Verify")', '[role="button"]:has-text("Confirm")',
                        '[role="button"]:has-text("Continue")', '[role="button"]:has-text("CONTINUE")',
                    ):
                        try:
                            el = await browser.page.query_selector(sel)
                            if el and await el.is_visible():
                                try:
                                    if hasattr(el, "is_enabled") and not await el.is_enabled():
                                        continue
                                except Exception:
                                    pass
                                await el.click()
                                verify_clicked = True
                                logger.info(f"Кнопка подтверждения кода нажата: {sel}")
                                break
                        except Exception:
                            continue
                if not verify_clicked:
                    try:
                        verify_btn = browser.page.get_by_role("button", name=re.compile(r"verify|confirm|continue|submit", re.I))
                        if await verify_btn.count() > 0:
                            await verify_btn.first.click()
                            verify_clicked = True
                            logger.info("Кнопка подтверждения кода нажата (get_by_role)")
                    except Exception as e:
                        logger.debug(f"get_by_role для Verify: {e}")
                if not verify_clicked:
                    try:
                        clicked = await browser.page.evaluate("""() => {
                            const want = ['VERIFY', 'CONFIRM', 'CONTINUE', 'SUBMIT'];
                            const btns = document.querySelectorAll('button, [role="button"], input[type="submit"]');
                            for (const b of btns) {
                                const t = (b.value || b.textContent || '').trim().toUpperCase();
                                if (t.includes('CANCEL')) continue;
                                const aria = (b.getAttribute('aria-disabled') || '').toLowerCase();
                                const disabled = b.disabled || aria === 'true';
                                if (want.some(w => t.includes(w)) && b.offsetParent && !disabled) {
                                    b.click();
                                    return true;
                                }
                            }
                            return false;
                        }""")
                        if clicked:
                            verify_clicked = True
                            logger.info("Кнопка подтверждения кода нажата (JS)")
                    except Exception as e:
                        logger.debug(f"Клик по кнопке Verify через JS: {e}")
                if not verify_clicked:
                    logger.warning("Кнопка Verify не найдена — отправка только по Enter")
                await browser.page.wait_for_timeout(5000)
            elif six_digit_inputs:
                await browser.human_like_delay(300, 600)
                for idx, inp in enumerate(six_digit_inputs):
                    if idx < len(verification_code):
                        await inp.fill(verification_code[idx])
                        await browser.human_like_delay(80, 150)
                await browser.take_screenshot(f"supercell_code_filled_{session_id}.png")
                await browser.human_like_delay(400, 800)
                verify_clicked_6 = False
                await browser.page.keyboard.press("Enter")
                await browser.page.wait_for_timeout(2000)
                try:
                    if "store.supercell.com" in browser.page.url and "login" not in browser.page.url.lower():
                        verify_clicked_6 = True
                        logger.info("Отправка по Enter (6 полей) — редирект на store")
                except Exception:
                    pass
                if not verify_clicked_6:
                    for sel in ('button:has-text("VERIFY")', 'button:has-text("Verify")', 'button:has-text("Confirm")', 'button:has-text("Submit")', 'button[type="submit"]'):
                        try:
                            el = await browser.page.query_selector(sel)
                            if el and await el.is_visible():
                                await el.click()
                                logger.info(f"Кнопка подтверждения нажата (6 полей): {sel}")
                                break
                        except Exception:
                            continue
                await browser.page.wait_for_timeout(5000)
            else:
                logger.warning("Поле для кода не найдено, пробуем ввести код в любое текстовое поле")
                # Пробуем найти любое текстовое поле (даём время на догрузку)
                try:
                    text_input = await browser.page.wait_for_selector('input[type="text"]', timeout=30000)
                    if text_input:
                        await browser.page.fill('input[type="text"]', verification_code)
                        await browser.page.keyboard.press("Enter")
                        await browser.page.wait_for_timeout(5000)
                except Exception:
                    pass

        # Ждем завершения авторизации и редиректа после ввода OTP кода
        logger.info("Ожидание завершения авторизации после ввода OTP кода...")
        await browser.page.wait_for_timeout(8000)
        
        # Ждем редирект на store.supercell.com (при успешном входе) — до 45 сек
        try:
            await browser.page.wait_for_url(
                lambda url: "store.supercell.com" in url and "login" not in url.lower(),
                timeout=45000,
            )
            logger.info("Редирект на store.supercell.com выполнен")
        except Exception:
            logger.debug("Редирект на store.supercell.com не произошел за 45 сек, проверяем страницу...")
        
        await browser.page.wait_for_timeout(3000)
        
        # Ждем навигации или изменения страницы
        try:
            await browser.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await browser.page.wait_for_timeout(2000)
        
        # Проверяем успешность авторизации
        current_url = browser.page.url
        logger.info(f"Текущий URL после ввода OTP: {current_url}")

        # Получаем текст страницы для анализа
        page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")
        
        # Проверяем на ошибки ввода кода
        error_indicators = [
            "invalid code",
            "incorrect code",
            "wrong code",
            "code expired",
            "неверный код",
            "неправильный код",
            "код истек",
            "try again",
            "попробуйте снова",
        ]
        
        has_error = any(indicator in page_text for indicator in error_indicators)
        if has_error:
            await browser.take_screenshot(f"supercell_code_error_{session_id}.png")
            logger.warning("Обнаружена ошибка при вводе OTP кода")
            raise Exception(
                "Неверный или истекший код верификации. "
                "Проверьте код в email и попробуйте снова."
            )

        # Проверяем признаки успешной авторизации
        # 1. URL указывает на store.supercell.com и не содержит login/signin
        url_check = (
            "store.supercell.com" in current_url
            and "login" not in current_url.lower()
            and "signin" not in current_url.lower()
            and "auth" not in current_url.lower()
        )
        
        # 2. На странице есть признаки авторизованного пользователя (в т.ч. на accounts.supercell.com)
        page_content_check = any([
            "welcome" in page_text,
            "profile" in page_text,
            "account" in page_text,
            "dashboard" in page_text,
            "my account" in page_text,
            "logout" in page_text,
            "sign out" in page_text,
            "выйти" in page_text,
            "supercell id" in page_text and "log in" not in page_text and "verification" not in page_text,
        ])
        
        # Успех может быть на той же странице /login (после Verify контент меняется)
        same_page_success = (
            "accounts.supercell.com" in current_url
            and not has_error
            and ("logout" in page_text or "sign out" in page_text or "account" in page_text)
            and "verification code" not in page_text
            and "enter the code" not in page_text
        )
        
        # 3. Проверяем наличие элементов, характерных для авторизованной страницы
        authenticated_elements = [
            'a:has-text("Log out")',
            'a:has-text("Sign out")',
            'a:has-text("Account")',
            'a:has-text("Profile")',
            '[href*="logout"]',
            '[href*="account"]',
            '[href*="profile"]',
        ]
        
        has_auth_elements = False
        for selector in authenticated_elements:
            try:
                element = await browser.page.query_selector(selector)
                if element and await element.is_visible():
                    has_auth_elements = True
                    logger.info(f"Найден элемент авторизованного пользователя: {selector}")
                    break
            except Exception:
                continue

        authenticated = url_check or page_content_check or has_auth_elements or same_page_success
        
        if authenticated:
            logger.info("✅ Авторизация в Supercell Store успешна!")
        else:
            logger.warning("⚠️ Не удалось подтвердить успешную авторизацию")

        # Скриншот итоговой страницы (с залогиненным аккаунтом или текущим состоянием)
        await browser.page.wait_for_timeout(1500)
        screenshot_path = await browser.take_screenshot(
            f"supercell_login_result_{session_id}.png"
        )

        # Дополнительная проверка: если мы все еще на странице входа, но нет ошибок
        if not authenticated:
            # Проверяем, может быть страница еще загружается
            await browser.page.wait_for_timeout(3000)
            current_url = browser.page.url
            page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")
            
            # Повторная проверка
            url_check = (
                "store.supercell.com" in current_url
                and "login" not in current_url.lower()
                and "signin" not in current_url.lower()
            )
            page_content_check = any([
                "welcome" in page_text,
                "profile" in page_text,
                "account" in page_text,
            ])
            
            if url_check or page_content_check:
                authenticated = True
                logger.info("✅ Авторизация подтверждена после дополнительной проверки")

        result = {
            "success": authenticated,
            "session_id": session_id,
            "email": request.email,
            "authenticated": authenticated,
            "screenshot": str(screenshot_path),
            "url": current_url,
            "message": "Авторизация в Supercell Store успешна"
            if authenticated
            else "Требуется дополнительная верификация или проверка данных. Проверьте скриншот и видео для деталей.",
        }

        # Закрываем браузер, чтобы сохранить запись видео и отдать путь в ответе
        try:
            video_path = await browser.close()
            if video_path:
                result["video"] = video_path
        except Exception as close_err:
            logger.debug(f"Ошибка при закрытии браузера: {close_err}")
        return result

    except Exception as e:
        logger.error(f"Ошибка авторизации в Supercell Store: {e}")
        screenshot_path = None
        try:
            if browser.page:
                screenshot_path = await browser.take_screenshot(
                    f"supercell_login_error_{session_id}.png"
                )
        except Exception:
            pass
        video_path = None
        try:
            video_path = await browser.close()
        except Exception:
            pass
        raise Exception(str(e))


@router.post("/supercell/link-google")
async def link_google_account(request: LinkGoogleAccountRequest):
    """
    Привязка Google аккаунта к Supercell Store аккаунту.

    Args:
        request: Данные для привязки Google аккаунта

    Returns:
        Результат привязки
    """
    browser = BrowserAutomation()
    session_id = f"link_google_{request.supercell_email.replace('@', '_at_')}"

    try:
        logger.info(
            f"Начало привязки Google аккаунта {request.google_email} к Supercell {request.supercell_email}"
        )

        # Запускаем браузер
        await browser.start()

        # Сначала авторизуемся в Supercell Store (если нужно)
        await browser.page.goto(
            "https://store.supercell.com", wait_until="domcontentloaded", timeout=60000
        )
        await browser.page.wait_for_timeout(2000)
        await browser.take_screenshot(f"supercell_link_google_start_{session_id}.png")

        # Проверяем, авторизованы ли мы
        current_url = browser.page.url
        page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")

        is_logged_in = (
            "login" not in current_url.lower()
            and "signin" not in current_url.lower()
            and ("profile" in page_text or "account" in page_text or "welcome" in page_text)
        )

        if not is_logged_in:
            # Нужно сначала авторизоваться
            logger.info("Требуется авторизация в Supercell Store")
            # Здесь можно вызвать supercell_login или просто перейти на страницу входа
            # Для упрощения предполагаем, что пользователь уже авторизован
            raise Exception(
                "Требуется сначала авторизоваться в Supercell Store. Используйте /supercell/login"
            )

        # Ищем настройки аккаунта или привязку Google
        # Обычно это в профиле или настройках
        settings_selectors = [
            'a:has-text("Settings")',
            'a:has-text("Account")',
            'a:has-text("Profile")',
            '[href*="settings"]',
            '[href*="account"]',
            '[href*="profile"]',
            '.account-settings',
            '#account-settings',
        ]

        settings_clicked = False
        for selector in settings_selectors:
            try:
                await browser.page.click(selector, timeout=5000)
                settings_clicked = True
                logger.info(f"Настройки найдены: {selector}")
                break
            except Exception:
                continue

        if settings_clicked:
            await browser.page.wait_for_timeout(2000)
            await browser.take_screenshot(f"supercell_settings_{session_id}.png")

        # Ищем опцию привязки Google аккаунта
        link_google_selectors = [
            'button:has-text("Link Google")',
            'button:has-text("Connect Google")',
            'a:has-text("Link Google")',
            'a:has-text("Connect Google")',
            '[href*="google"]',
            'button[data-provider="google"]',
        ]

        link_clicked = False
        for selector in link_google_selectors:
            try:
                await browser.page.click(selector, timeout=5000)
                link_clicked = True
                logger.info(f"Кнопка привязки Google найдена: {selector}")
                break
            except Exception:
                continue

        if not link_clicked:
            # Пробуем найти через текст
            try:
                await browser.page.click('text=Google', timeout=5000)
                link_clicked = True
            except Exception:
                pass

        if link_clicked:
            await browser.page.wait_for_timeout(3000)
            await browser.take_screenshot(f"supercell_google_link_clicked_{session_id}.png")

        # Теперь должна открыться страница авторизации Google
        # Ждем перехода на Google
        await browser.page.wait_for_timeout(3000)

        # Проверяем, перешли ли на Google
        current_url = browser.page.url
        if "accounts.google.com" in current_url or "google.com" in current_url:
            logger.info("Переход на страницу авторизации Google выполнен")

            # Авторизуемся в Google
            # Ищем поле email
            google_email_selectors = [
                'input[type="email"]',
                'input[name="identifier"]',
                'input[id="identifierId"]',
                '#identifierId',
            ]

            google_email_input = None
            found_google_email_selector = None
            for selector in google_email_selectors:
                try:
                    google_email_input = await browser.page.wait_for_selector(
                        selector, timeout=10000
                    )
                    if google_email_input:
                        found_google_email_selector = selector
                        break
                except Exception:
                    continue

            if google_email_input:
                await browser.page.fill(found_google_email_selector, request.google_email)
                await browser.take_screenshot(
                    f"supercell_google_email_filled_{session_id}.png"
                )

                # Нажимаем Next
                next_selectors = [
                    'button:has-text("Next")',
                    '#identifierNext',
                    'button[type="submit"]',
                ]

                for selector in next_selectors:
                    try:
                        await browser.page.click(selector, timeout=3000)
                        break
                    except Exception:
                        continue

                await browser.page.wait_for_timeout(3000)

                # Если нужен пароль
                if request.google_password:
                    password_selectors = [
                        'input[type="password"]',
                        'input[name="password"]',
                        'input[name="Passwd"]',
                    ]

                    password_input = None
                    found_password_selector = None
                    for selector in password_selectors:
                        try:
                            password_input = await browser.page.wait_for_selector(
                                selector, timeout=15000
                            )
                            if password_input:
                                found_password_selector = selector
                                break
                        except Exception:
                            continue

                    if password_input:
                        await browser.page.fill(found_password_selector, request.google_password)
                        await browser.take_screenshot(
                            f"supercell_google_password_filled_{session_id}.png"
                        )

                        # Нажимаем Next
                        for selector in next_selectors:
                            try:
                                await browser.page.click(selector, timeout=3000)
                                break
                            except Exception:
                                continue

                        await browser.page.wait_for_timeout(5000)

                # Ждем возврата на Supercell Store или подтверждения
                await browser.page.wait_for_timeout(5000)
                await browser.take_screenshot(
                    f"supercell_google_linked_{session_id}.png"
                )

        # Проверяем успешность привязки
        final_url = browser.page.url
        final_page_text = await browser.page.evaluate(
            "() => document.body.innerText.toLowerCase()"
        )

        linked = (
            "store.supercell.com" in final_url
            and ("google" in final_page_text or "connected" in final_page_text)
        ) or "accounts.google.com" not in final_url

        result = {
            "success": linked,
            "supercell_email": request.supercell_email,
            "google_email": request.google_email,
            "linked": linked,
            "screenshot": f"supercell_google_linked_{session_id}.png",
            "url": final_url,
            "message": "Google аккаунт успешно привязан к Supercell Store"
            if linked
            else "Требуется дополнительная верификация",
        }

        await browser.close()
        return result

    except Exception as e:
        logger.error(f"Ошибка привязки Google аккаунта: {e}")
        screenshot_path = None
        try:
            if browser.page:
                screenshot_path = await browser.take_screenshot(
                    f"supercell_link_google_error_{session_id}.png"
                )
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "screenshot": str(screenshot_path) if screenshot_path else None,
            },
        )


@router.post("/supercell/full-auth")
async def full_supercell_auth(
    supercell_email: EmailStr = Body(...),
    supercell_email_password: Optional[str] = Body(None),  # Пароль для доступа к email Supercell
    supercell_verification_code: Optional[str] = Body(None),  # Код верификации Supercell (если уже известен)
    supercell_code: Optional[str] = Body(None, alias="supercell_code"),  # Алиас для supercell_verification_code (из демо)
    google_email: EmailStr = Body(...),
    google_password: Optional[str] = Body(None),
):
    """
    Полный процесс: авторизация в Supercell Store + привязка Google аккаунта.

    Args:
        supercell_email: Email аккаунта Supercell
        supercell_email_password: Пароль для доступа к email Supercell (для получения кода)
        supercell_verification_code: Код верификации Supercell (если уже известен)
        google_email: Email Google аккаунта
        google_password: Пароль Google (опционально, если уже авторизован)

    Returns:
        Результат полной авторизации
    """
    browser = BrowserAutomation()
    session_id = f"full_auth_{supercell_email.replace('@', '_at_')}"

    logger.info(
        f"Получен full-auth: supercell_email={supercell_email}, "
        f"supercell_verification_code={'***' + (supercell_verification_code or '')[-2:] if supercell_verification_code else None}, "
        f"google_email={google_email}, supercell_email_password={'***' if supercell_email_password else None}, "
        f"google_password={'***' if google_password else None}"
    )

    try:
        logger.info(
            f"Начало полной авторизации: Supercell {supercell_email} + Google {google_email}"
        )

        # Шаг 1: Авторизация в Supercell Store
        await browser.start()

        await browser.page.goto(
            "https://store.supercell.com", wait_until="domcontentloaded", timeout=60000
        )
        await browser.page.wait_for_timeout(3000)
        
        # Принимаем cookies
        await _accept_cookies(browser)
        
        await browser.take_screenshot(f"full_auth_step1_store_{session_id}.png")

        # Ищем кнопку входа
        login_selectors = [
            'a:has-text("Log in")',
            'button:has-text("Log in")',
            '[href*="login"]',
            'text=Log in',
        ]

        for selector in login_selectors:
            try:
                await browser.page.click(selector, timeout=5000)
                break
            except Exception:
                continue

        await browser.page.wait_for_timeout(2000)
        await browser.take_screenshot(f"full_auth_step2_login_clicked_{session_id}.png")

        # Вводим email Supercell
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[name="username"]',
        ]

        email_filled = False
        for selector in email_selectors:
            try:
                await browser.page.fill(selector, supercell_email)
                email_filled = True
                break
            except Exception:
                continue

        if not email_filled:
            raise Exception("Не удалось найти поле email Supercell")

        await browser.take_screenshot(f"full_auth_step3_email_filled_{session_id}.png")

        # Нажимаем Next/Continue
        continue_selectors = [
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button[type="submit"]',
        ]
        
        for selector in continue_selectors:
            try:
                element = await browser.page.query_selector(selector)
                if element and await element.is_visible():
                    await element.click()
                    break
            except Exception:
                continue
        
        if not any(await browser.page.query_selector(s) for s in continue_selectors):
            await browser.page.keyboard.press("Enter")
        
        # После отправки email Supercell перенаправляет на /verify — ждём этот редирект
        logger.info("Краткое ожидание редиректа на /verify (15 сек), иначе форма кода на /login (SPA)...")
        try:
            await browser.page.wait_for_url(
                lambda url: "accounts.supercell.com" in url and "/verify" in url,
                timeout=15000,
            )
            logger.info("Редирект на /verify выполнен (full-auth)")
        except Exception:
            logger.info("Редирект на /verify не произошёл — форма кода на /login, продолжаем")
        await browser.page.wait_for_timeout(3000)
        await browser.take_screenshot(f"full_auth_step3_after_email_{session_id}.png")

        # Получаем код верификации: supercell_verification_code или алиас supercell_code (как в демо)
        verification_code = supercell_verification_code or supercell_code
        
        # Нормализуем код верификации (убираем пробелы и дефисы)
        if verification_code:
            verification_code = verification_code.replace(" ", "").replace("-", "").strip()
            logger.info(f"full-auth: получен supercell_verification_code, после нормализации длина={len(verification_code)}, последние 2 цифры=***{verification_code[-2:]}")
            if len(verification_code) != 6 or not verification_code.isdigit():
                raise Exception(
                    f"Неверный формат кода верификации. "
                    f"Код должен быть 6 цифр, получено: '{supercell_verification_code}'"
                )
        
        if not verification_code and supercell_email_password:
            logger.info("Ожидание кода верификации из email...")
            try:
                email_reader = EmailCodeReader(supercell_email, supercell_email_password)
                verification_code = email_reader.get_supercell_code(timeout=120)
                
                if not verification_code:
                    await browser.take_screenshot(f"full_auth_step4_code_not_received_{session_id}.png")
                    raise Exception(
                        "Код верификации не получен из email. "
                        "Возможные причины:\n"
                        "1. Письмо от Supercell еще не пришло (подождите 1-2 минуты)\n"
                        "2. Проверьте папку 'Спам' в почте\n"
                        "3. Неверные учетные данные для доступа к email\n"
                        "4. Для Gmail с включенной 2FA требуется App Password\n"
                        "Проверьте правильность email и пароля."
                    )
            except Exception as e:
                await browser.take_screenshot(f"full_auth_email_error_{session_id}.png")
                raise Exception(str(e))
        elif not verification_code:
            # Код не передан и пароль для email тоже не передан
            await browser.take_screenshot(f"full_auth_no_code_{session_id}.png")
            raise Exception(
                "Код верификации не предоставлен. "
                "Введите код верификации из письма Supercell в поле 'supercell_verification_code' или "
                "предоставьте 'supercell_email_password' для автоматического получения кода из email."
            )

        if verification_code:
            logger.info(f"Используем код верификации: {verification_code[:2]}**")
            
            # Ищем поле для кода верификации (форма может грузиться долго — первый селектор до 90 сек)
            code_selectors = [
                'input[type="text"][maxlength="6"]',
                'input[type="text"][maxlength="7"]',
                'input[type="number"]',
                'input[name*="code"]',
                'input[name*="verification"]',
                'input[id*="code"]',
                'input[id*="verification"]',
                'input[placeholder*="code" i]',
            ]

            code_filled = False
            for i, selector in enumerate(code_selectors):
                timeout_ms = 90000 if i == 0 else 15000
                try:
                    code_input = await browser.page.wait_for_selector(selector, timeout=timeout_ms)
                    if code_input:
                        await browser.page.fill(selector, verification_code)
                        code_filled = True
                        logger.info(f"Код введен через селектор: {selector}")
                        break
                except Exception:
                    continue

            if code_filled:
                await browser.take_screenshot(f"full_auth_step4_code_filled_{session_id}.png")
                
                # Нажимаем кнопку подтверждения
                submit_selectors = [
                    'button:has-text("Verify")',
                    'button:has-text("Confirm")',
                    'button[type="submit"]',
                ]
                
                for selector in submit_selectors:
                    try:
                        element = await browser.page.query_selector(selector)
                        if element and await element.is_visible():
                            await element.click()
                            break
                    except Exception:
                        continue
                
                await browser.page.wait_for_timeout(5000)

        await browser.take_screenshot(f"full_auth_step5_supercell_logged_{session_id}.png")

        # Шаг 2: Привязка Google аккаунта
        # Ищем настройки/профиль
        settings_selectors = [
            'a:has-text("Settings")',
            'a:has-text("Account")',
            '[href*="settings"]',
            '[href*="account"]',
        ]

        for selector in settings_selectors:
            try:
                await browser.page.click(selector, timeout=5000)
                await browser.page.wait_for_timeout(2000)
                break
            except Exception:
                continue

        await browser.take_screenshot(f"full_auth_step6_settings_{session_id}.png")

        # Ищем привязку Google
        google_link_selectors = [
            'button:has-text("Link Google")',
            'button:has-text("Connect Google")',
            'a:has-text("Google")',
            '[href*="google"]',
        ]

        google_link_clicked = False
        for selector in google_link_selectors:
            try:
                await browser.page.click(selector, timeout=5000)
                google_link_clicked = True
                break
            except Exception:
                continue

        if google_link_clicked:
            await browser.page.wait_for_timeout(3000)
            await browser.take_screenshot(
                f"full_auth_step7_google_link_clicked_{session_id}.png"
            )

            # Авторизуемся в Google
            if "accounts.google.com" in browser.page.url:
                # Вводим Google email
                google_email_selectors = [
                    'input[type="email"]',
                    'input[id="identifierId"]',
                    '#identifierId',
                ]

                for selector in google_email_selectors:
                    try:
                        await browser.page.fill(selector, google_email)
                        break
                    except Exception:
                        continue

                await browser.take_screenshot(
                    f"full_auth_step8_google_email_{session_id}.png"
                )

                # Next
                await browser.page.click('#identifierNext, button:has-text("Next")', timeout=5000)
                await browser.page.wait_for_timeout(3000)

                # Вводим пароль Google (если нужен)
                if google_password:
                    password_selectors = [
                        'input[type="password"]',
                        'input[name="Passwd"]',
                    ]

                    for selector in password_selectors:
                        try:
                            await browser.page.fill(selector, google_password)
                            break
                        except Exception:
                            continue

                    await browser.take_screenshot(
                        f"full_auth_step9_google_password_{session_id}.png"
                    )

                    # Next
                    await browser.page.click(
                        '#passwordNext, button:has-text("Next")', timeout=5000
                    )
                    await browser.page.wait_for_timeout(5000)

        # Финальная проверка
        await browser.page.wait_for_timeout(3000)
        final_url = browser.page.url
        final_screenshot = await browser.take_screenshot(
            f"full_auth_step10_final_{session_id}.png"
        )

        # Проверяем успешность
        success = (
            "store.supercell.com" in final_url
            and "accounts.google.com" not in final_url
        )

        result = {
            "success": success,
            "supercell_email": supercell_email,
            "google_email": google_email,
            "screenshots": [
                f"full_auth_step1_store_{session_id}.png",
                f"full_auth_step2_login_clicked_{session_id}.png",
                f"full_auth_step3_email_filled_{session_id}.png",
                f"full_auth_step5_supercell_logged_{session_id}.png",
                f"full_auth_step6_settings_{session_id}.png",
                f"full_auth_step7_google_link_clicked_{session_id}.png",
                f"full_auth_step8_google_email_{session_id}.png",
                f"full_auth_step10_final_{session_id}.png",
            ],
            "final_url": final_url,
            "message": "Полная авторизация и привязка Google выполнены успешно"
            if success
            else "Процесс завершён, требуется проверка",
        }

        await browser.close()
        return result

    except Exception as e:
        logger.error(f"Ошибка полной авторизации: {e}")
        screenshot_path = None
        try:
            if browser.page:
                screenshot_path = await browser.take_screenshot(
                    f"full_auth_error_{session_id}.png"
                )
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "screenshot": str(screenshot_path) if screenshot_path else None,
            },
        )

"""API routes для авторизации и управления аккаунтами."""

import re
from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, List
from loguru import logger
from app.core.browser_automation import BrowserAutomation
from app.core.payment_handler import PaymentHandler

router = APIRouter()


class GoogleAuthRequest(BaseModel):
    """Запрос на авторизацию в Google аккаунте."""

    email: EmailStr
    password: Optional[str] = None
    use_existing_session: bool = False


class GooglePayCardRequest(BaseModel):
    """Запрос на привязку карты к Google Pay."""

    email: EmailStr
    card_number: str
    card_exp_month: int
    card_exp_year: int
    card_cvv: Optional[str] = None
    cardholder_name: Optional[str] = None


class SessionInfo(BaseModel):
    """Информация о сессии браузера."""

    session_id: str
    email: str
    authenticated: bool
    google_pay_cards: List[Dict]
    screenshots: List[str]


@router.post("/google/login")
async def google_login(request: GoogleAuthRequest):
    """
    Авторизация в Google аккаунте через браузер.

    Args:
        request: Данные для авторизации

    Returns:
        Информация о сессии
    """
    browser = BrowserAutomation()
    session_id = f"session_{request.email.replace('@', '_at_')}"

    try:
        logger.info(f"Начало авторизации для {request.email}")

        # Запускаем браузер
        await browser.start()

        # Переходим на страницу входа Google
        await browser.page.goto(
            "https://accounts.google.com/signin", wait_until="domcontentloaded", timeout=60000
        )
        await browser.page.wait_for_timeout(2000)  # Дополнительное ожидание загрузки
        await browser.take_screenshot(f"google_login_start_{session_id}.png")

        # Ждем появления поля email с несколькими вариантами селекторов
        email_selectors = [
            'input[type="email"]',
            'input[name="identifier"]',
            'input[id="identifierId"]',
            '#identifierId',
            'input[aria-label*="email" i]',
        ]
        
        email_input = None
        for selector in email_selectors:
            try:
                email_input = await browser.page.wait_for_selector(selector, timeout=5000)
                if email_input:
                    logger.info(f"Найдено поле email: {selector}")
                    break
            except Exception:
                continue
        
        if not email_input:
            raise Exception("Поле email не найдено на странице")
        
        # Вводим email (используем первый найденный селектор)
        found_selector = None
        for selector in email_selectors:
            try:
                element = await browser.page.query_selector(selector)
                if element:
                    found_selector = selector
                    break
            except Exception:
                continue
        
        if not found_selector:
            found_selector = email_selectors[0]
        
        await browser.page.fill(found_selector, request.email)
        await browser.take_screenshot(f"google_login_email_filled_{session_id}.png")
        
        # Ищем кнопку "Next" с несколькими вариантами
        next_button_selectors = [
            'button:has-text("Next")',
            'button:has-text("Далее")',
            'button[type="submit"]',
            '#identifierNext',
            'button[id*="Next"]',
            'div[role="button"]:has-text("Next")',
        ]
        
        next_clicked = False
        for selector in next_button_selectors:
            try:
                await browser.page.click(selector, timeout=3000)
                next_clicked = True
                logger.info(f"Кнопка Next найдена: {selector}")
                break
            except Exception:
                continue
        
        if not next_clicked:
            await browser.page.keyboard.press("Enter")

        # Ждём перехода на шаг пароля (v3: .../challenge/pwd или v2: .../challenge)
        try:
            await browser.page.wait_for_url(
                lambda u: "challenge/pwd" in u or "pwd" in u or "challenge" in u,
                timeout=20000,
            )
        except Exception:
            pass
        await browser.page.wait_for_timeout(2000)
        await browser.take_screenshot(f"google_login_email_{session_id}.png")

        if request.password:
            # Селекторы для страницы пароля Google (v2 и v3), включая "Enter your password"
            password_selectors = [
                'input[type="password"]',
                'input[aria-label*="Enter your password" i]',
                'input[aria-label*="password" i]',
                'input[aria-label*="пароль" i]',
                'input[name="Passwd"]',
                'input[name="password"]',
                'input[autocomplete="current-password"]',
                '#password input',
                '#password',
            ]
            password_input = None
            found_password_selector = None
            for selector in password_selectors:
                try:
                    el = await browser.page.wait_for_selector(
                        selector, timeout=12000, state="visible"
                    )
                    if el:
                        is_visible = await el.is_visible()
                        if is_visible:
                            password_input = el
                            found_password_selector = selector
                            logger.info(f"Найдено поле пароля: {selector}")
                            break
                except Exception:
                    continue

            # Fallback: getByLabel / getByRole для "Enter your password"
            if not password_input and not found_password_selector:
                for label_text in ["Enter your password", "password", "Введите пароль", "Пароль"]:
                    try:
                        loc = browser.page.get_by_label(re.compile(re.escape(label_text), re.I))
                        await loc.first.wait_for(state="visible", timeout=5000)
                        password_input = True
                        found_password_selector = "__getByLabel__"
                        logger.info(f"Поле пароля найдено через getByLabel: {label_text}")
                        break
                    except Exception:
                        continue
            if not password_input and not found_password_selector:
                try:
                    loc = browser.page.get_by_role(
                        "textbox", name=re.compile(r"password|пароль|passwd|enter your password", re.I)
                    )
                    await loc.first.wait_for(state="visible", timeout=8000)
                    password_input = True
                    found_password_selector = "__locator__"
                    logger.info("Поле пароля найдено через getByRole(textbox)")
                except Exception as e:
                    logger.debug(f"getByRole для пароля не сработал: {e}")

            if password_input and found_password_selector:
                if found_password_selector == "__getByLabel__":
                    # Используем тот же текст, который сработал (первый из списка, который найдётся при повторе)
                    for label_text in ["Enter your password", "password", "Введите пароль", "Пароль"]:
                        try:
                            loc = browser.page.get_by_label(re.compile(re.escape(label_text), re.I))
                            await loc.first.fill(request.password)
                            break
                        except Exception:
                            continue
                elif found_password_selector == "__locator__":
                    loc = browser.page.get_by_role(
                        "textbox", name=re.compile(r"password|пароль|passwd|enter your password", re.I)
                    )
                    await loc.first.fill(request.password)
                else:
                    await browser.page.fill(found_password_selector, request.password)
                # Если fill не сработал — симулируем ввод с клавиатуры (триггерит события Google)
                try:
                    pwd_el = await browser.page.query_selector('input[type="password"]')
                    if pwd_el:
                        cur_val = await browser.page.evaluate("el => el.value", pwd_el)
                        if not cur_val or len(cur_val) == 0:
                            await pwd_el.click()
                            await browser.page.keyboard.type(request.password, delay=50)
                except Exception:
                    pass
                await browser.take_screenshot(f"google_login_password_filled_{session_id}.png")
                password_next_clicked = False
                for selector in next_button_selectors:
                    try:
                        await browser.page.click(selector, timeout=3000)
                        password_next_clicked = True
                        break
                    except Exception:
                        continue
                if not password_next_clicked:
                    await browser.page.keyboard.press("Enter")
                await browser.page.wait_for_timeout(5000)
                await browser.take_screenshot(f"google_login_password_{session_id}.png")
            else:
                logger.warning("Поле пароля не найдено, возможно требуется дополнительная верификация")
                await browser.take_screenshot(f"google_login_no_password_field_{session_id}.png")
                page_text = await browser.page.evaluate("() => document.body.innerText")
                if "captcha" in page_text.lower() or "verify" in page_text.lower():
                    raise Exception("Требуется капча или дополнительная верификация")

        # Проверяем успешность авторизации
        await browser.page.wait_for_timeout(3000)
        current_url = browser.page.url
        
        # Получаем текст страницы для анализа
        page_text = await browser.page.evaluate("() => document.body.innerText.toLowerCase()")
        
        # Проверяем различные признаки успешной авторизации
        authenticated = (
            "myaccount.google.com" in current_url or
            "accounts.google.com/signin/v2/challenge" not in current_url or
            "welcome" in page_text or
            "home" in page_text
        )
        
        # Проверяем на наличие проблем
        requires_verification = (
            "verify" in page_text or
            "captcha" in page_text or
            "challenge" in current_url or
            "2-step" in page_text
        )
        
        screenshot_path = await browser.take_screenshot(f"google_login_result_{session_id}.png")
        
        # Формируем сообщение
        if authenticated:
            message = "Авторизация успешна"
        elif requires_verification:
            message = "Требуется дополнительная верификация (капча, 2FA или подтверждение)"
        else:
            message = f"Авторизация не завершена. URL: {current_url}"

        result = {
            "success": authenticated,
            "session_id": session_id,
            "email": request.email,
            "authenticated": authenticated,
            "screenshot": str(screenshot_path),
            "url": current_url,
            "message": message,
            "requires_verification": requires_verification,
        }

        # Не закрываем браузер сразу - может понадобиться для дальнейших операций
        # await browser.close()

        return result

    except Exception as e:
        logger.error(f"Ошибка авторизации Google: {e}")
        screenshot_path = None
        try:
            if browser.page:
                screenshot_path = await browser.take_screenshot(f"google_login_error_{session_id}.png")
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


@router.post("/google/pay/add-card")
async def add_google_pay_card(request: GooglePayCardRequest):
    """
    Привязка карты к Google Pay через браузер.

    Args:
        request: Данные карты

    Returns:
        Результат привязки карты
    """
    browser = BrowserAutomation()
    session_id = f"session_{request.email.replace('@', '_at_')}"

    try:
        logger.info(f"Начало привязки карты для {request.email}")

        # Запускаем браузер
        await browser.start()

        # Переходим в Google Pay
        await browser.page.goto(
            "https://pay.google.com/paymentmethods", wait_until="networkidle"
        )
        await browser.take_screenshot(f"google_pay_start_{session_id}.png")

        # Если требуется авторизация
        if "accounts.google.com" in browser.page.url:
            # Пытаемся авторизоваться
            await browser.page.fill('input[type="email"]', request.email)
            await browser.page.click('button:has-text("Next")')
            await browser.page.wait_for_timeout(2000)
            await browser.take_screenshot(f"google_pay_auth_{session_id}.png")

        # Ищем кнопку добавления карты
        add_card_selectors = [
            'button:has-text("Add payment method")',
            'button:has-text("Add card")',
            'a[href*="addcard"]',
            '[data-testid="add-card"]',
        ]

        card_added = False
        for selector in add_card_selectors:
            try:
                await browser.page.click(selector, timeout=5000)
                await browser.take_screenshot(f"google_pay_add_card_click_{session_id}.png")
                card_added = True
                break
            except Exception:
                continue

        if not card_added:
            raise Exception("Кнопка добавления карты не найдена")

        await browser.page.wait_for_timeout(2000)

        # Заполняем данные карты
        card_number_input = await browser.page.wait_for_selector(
            'input[name="cardNumber"], input[placeholder*="card"], input[id*="card"]',
            timeout=10000,
        )

        if card_number_input:
            await browser.page.fill(
                'input[name="cardNumber"], input[placeholder*="card"]', request.card_number
            )
            await browser.take_screenshot(f"google_pay_card_number_{session_id}.png")

            # Заполняем срок действия
            exp_inputs = await browser.page.query_selector_all(
                'input[name*="exp"], input[placeholder*="MM/YY"]'
            )
            if exp_inputs:
                exp_value = f"{request.card_exp_month:02d}/{request.card_exp_year % 100}"
                await browser.page.fill('input[name*="exp"], input[placeholder*="MM/YY"]', exp_value)

            # Заполняем CVV если есть
            if request.card_cvv:
                cvv_input = await browser.page.query_selector(
                    'input[name*="cvv"], input[name*="cvc"], input[placeholder*="CVV"]'
                )
                if cvv_input:
                    await browser.page.fill(
                        'input[name*="cvv"], input[name*="cvc"]', request.card_cvv
                    )

            # Заполняем имя если есть
            if request.cardholder_name:
                name_input = await browser.page.query_selector(
                    'input[name*="name"], input[placeholder*="Name"]'
                )
                if name_input:
                    await browser.page.fill('input[name*="name"]', request.cardholder_name)

            await browser.take_screenshot(f"google_pay_card_filled_{session_id}.png")

            # Сохраняем карту
            save_button = await browser.page.query_selector(
                'button:has-text("Save"), button:has-text("Add"), button[type="submit"]'
            )
            if save_button:
                await save_button.click()
                await browser.page.wait_for_timeout(3000)
                await browser.take_screenshot(f"google_pay_card_saved_{session_id}.png")

        # Проверяем успешность привязки
        current_url = browser.page.url
        success = "paymentmethods" in current_url or "success" in current_url.lower()

        result = {
            "success": success,
            "email": request.email,
            "card_last4": request.card_number[-4:],
            "screenshots": [
                f"google_pay_start_{session_id}.png",
                f"google_pay_card_filled_{session_id}.png",
                f"google_pay_card_saved_{session_id}.png",
            ],
            "message": "Карта успешно привязана" if success else "Требуется дополнительная верификация",
        }

        await browser.close()
        return result

    except Exception as e:
        logger.error(f"Ошибка привязки карты: {e}")
        screenshot_path = None
        try:
            if browser.page:
                screenshot_path = await browser.take_screenshot(f"google_pay_error_{session_id}.png")
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


@router.get("/google/pay/cards")
async def get_google_pay_cards(email: EmailStr = Query(...)):
    """
    Получить список карт в Google Pay для аккаунта.

    Args:
        email: Email аккаунта

    Returns:
        Список карт
    """
    browser = BrowserAutomation()
    session_id = f"session_{email.replace('@', '_at_')}"

    try:
        await browser.start()

        # Переходим в Google Pay
        await browser.page.goto(
            "https://pay.google.com/paymentmethods", wait_until="networkidle"
        )

        # Если требуется авторизация
        if "accounts.google.com" in browser.page.url:
            await browser.page.fill('input[type="email"]', email)
            await browser.page.click('button:has-text("Next")')
            await browser.page.wait_for_timeout(3000)

        await browser.take_screenshot(f"google_pay_cards_list_{session_id}.png")

        # Извлекаем список карт со страницы
        cards = await browser.page.evaluate(
            """
            () => {
                const cardElements = document.querySelectorAll('[data-card], .card-item, [class*="card"]');
                const cards = [];
                cardElements.forEach(card => {
                    const last4 = card.textContent.match(/\\d{4}/g);
                    if (last4) {
                        cards.push({
                            last4: last4[last4.length - 1],
                            text: card.textContent.trim().substring(0, 100)
                        });
                    }
                });
                return cards.slice(0, 10);
            }
            """
        )

        result = {
            "email": email,
            "cards": cards,
            "screenshot": f"google_pay_cards_list_{session_id}.png",
        }

        await browser.close()
        return result

    except Exception as e:
        logger.error(f"Ошибка получения карт: {e}")
        screenshot_path = None
        try:
            if browser.page:
                screenshot_path = await browser.take_screenshot(f"google_pay_cards_error_{session_id}.png")
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


@router.post("/google/pay/remove-card")
async def remove_google_pay_card(
    email: EmailStr = Body(...), card_last4: str = Body(...)
):
    """
    Удалить карту из Google Pay.

    Args:
        email: Email аккаунта
        card_last4: Последние 4 цифры карты

    Returns:
        Результат удаления
    """
    browser = BrowserAutomation()
    session_id = f"session_{email.replace('@', '_at_')}"

    try:
        await browser.start()

        # Переходим в Google Pay
        await browser.page.goto(
            "https://pay.google.com/paymentmethods", wait_until="networkidle"
        )

        # Если требуется авторизация
        if "accounts.google.com" in browser.page.url:
            await browser.page.fill('input[type="email"]', email)
            await browser.page.click('button:has-text("Next")')
            await browser.page.wait_for_timeout(3000)

        await browser.take_screenshot(f"google_pay_remove_start_{session_id}.png")

        # Ищем карту по last4 и удаляем
        card_removed = await browser.page.evaluate(
            f"""
            () => {{
                const cards = document.querySelectorAll('[data-card], .card-item');
                for (let card of cards) {{
                    if (card.textContent.includes('{card_last4}')) {{
                        const removeBtn = card.querySelector('button:has-text("Remove"), button:has-text("Delete")');
                        if (removeBtn) {{
                            removeBtn.click();
                            return true;
                        }}
                    }}
                }}
                return false;
            }}
            """
        )

        if card_removed:
            await browser.page.wait_for_timeout(2000)
            await browser.take_screenshot(f"google_pay_remove_success_{session_id}.png")

        result = {
            "success": card_removed,
            "email": email,
            "card_last4": card_last4,
            "screenshot": f"google_pay_remove_success_{session_id}.png" if card_removed else f"google_pay_remove_start_{session_id}.png",
        }

        await browser.close()
        return result

    except Exception as e:
        logger.error(f"Ошибка удаления карты: {e}")
        screenshot_path = None
        try:
            if browser.page:
                screenshot_path = await browser.take_screenshot(f"google_pay_remove_error_{session_id}.png")
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

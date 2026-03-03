"""
Демо: браузер с прокси → ручной вход в аккаунт → автоматическая покупка и оплата через Google Pay.

Тот же процесс, что в purchase_demo.py, но без автоматической авторизации (вход в аккаунт вручную).

Запуск:
  python examples/manual_login_gpay_demo.py
  python examples/manual_login_gpay_demo.py --game brawl-stars --product "80 Gems"
  python examples/manual_login_gpay_demo.py --game clash-royale --product "500 Gems" --timeout 180
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Корень проекта в sys.path для импорта app при запуске из любой папки
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Включить видимый браузер до загрузки конфига
os.environ.setdefault("BROWSER_HEADLESS", "false")

from app.config import settings
from app.core.browser_automation import BrowserAutomation
from app.core.google_pay import handle_google_pay
from app.core.proxy_manager import proxy_manager
from app.api.store_routes import run_purchase_flow_after_login
from app.api.supercell_auth_routes import _accept_cookies
from loguru import logger


def print_step(step_num: int, title: str, description: str):
    """Вывести информацию о шаге (как в purchase_demo.py)."""
    print(f"\n{'='*60}")
    print(f"ШАГ {step_num}: {title}")
    print(f"{'='*60}")
    print(description)
    print()


async def _inject_2captcha_on_login_page(browser):
    """Получить токен 2Captcha и подставить на странице accounts.supercell.com/login."""
    page = browser.page if hasattr(browser, "page") else None
    if not page:
        return
    url = page.url or ""
    if "accounts.supercell.com" not in url or "/login" not in url:
        return
    api_key = (getattr(settings, "CAPTCHA_2CAPTCHA_API_KEY", "") or "").strip()
    if not api_key:
        return
    try:
        from app.core.recaptcha_solver import solve_recaptcha_enterprise
        token = await solve_recaptcha_enterprise(
            api_key=api_key,
            page_url=url,
            timeout=120,
        )
        if not token:
            return
        await page.evaluate(
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
            token,
        )
        try:
            await page.evaluate(
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
                token,
            )
        except Exception:
            pass
        logger.info("2Captcha: токен reCAPTCHA подставлен на странице входа (ручное демо)")
    except Exception as e:
        logger.debug("2Captcha при ручном входе: %s", e)


def _setup_2captcha_on_login_page(browser):
    """Включить подстановку 2Captcha при переходе на страницу входа Supercell."""
    api_key = (getattr(settings, "CAPTCHA_2CAPTCHA_API_KEY", "") or "").strip()
    if not api_key:
        return
    page = browser.page if hasattr(browser, "page") else None
    if not page:
        return

    def on_framenavigated(frame):
        try:
            if frame != page.main_frame:
                return
            url = frame.url or ""
            if "accounts.supercell.com" in url and "/login" in url:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_inject_2captcha_on_login_page(browser))
                except RuntimeError:
                    pass
        except Exception:
            pass

    try:
        page.on("framenavigated", on_framenavigated)
        logger.info("2Captcha: при переходе на страницу входа токен будет подставлен автоматически")
    except Exception as e:
        logger.debug("Не удалось подписаться на переход к странице входа: %s", e)


def check_proxy_status():
    """Проверка прокси (без API — по настройкам и proxy_manager)."""
    if not getattr(settings, "PROXY_ENABLED", False):
        print("   [Прокси] Не используются (PROXY_ENABLED=false).")
        return
    try:
        count = len(proxy_manager.proxies) if proxy_manager.proxies else 0
        if count > 0:
            proxy = proxy_manager.get_proxy()
            server = proxy.get("server", "unknown") if proxy else "?"
            print(f"   [Прокси] Загружено: {count}, будут использоваться при открытии браузера.")
            print(f"   [Прокси] Текущий: {server}")
        else:
            print("   [Прокси] Не настроены (proxies.txt пуст или не найден).")
    except Exception as e:
        print(f"   [Прокси] Ошибка: {e}")


def parse_args():
    p = argparse.ArgumentParser(description="Manual login + GPay purchase demo (без авто-авторизации)")
    p.add_argument("--game", default="brawl-stars", help="Game slug (e.g. brawl-stars, clash-royale)")
    p.add_argument("--product", default="80 Gems", help="Product name to search and buy")
    p.add_argument("--google-email", default="", help="Override Google Pay email from env")
    p.add_argument("--timeout", type=int, default=None, help="Payment timeout in seconds (default 300 for Google login)")
    return p.parse_args()


async def run_demo(
    game: str,
    product_name: str,
    google_email: str,
    payment_timeout: int,
    use_proxy: bool = True,
) -> dict:
    """Весь процесс покупки как в purchase_demo, без автоматической авторизации."""
    browser = BrowserAutomation()
    result = {
        "success": False,
        "added_to_cart": False,
        "checkout_opened": False,
        "message": "",
        "url": None,
        "screenshot": None,
        "checkout_screenshot": None,
        "video": None,
        "proxy_used": False,
        "proxy_server": None,
        "payment": {
            "google_pay_clicked": False,
            "payment_confirmed": False,
            "payment_verified": False,
            "success": False,
            "error": None,
        },
        "error": None,
    }

    try:
        # Шаг 1: Запуск браузера и переход на store
        print_step(
            1,
            "Запуск браузера и открытие Store",
            "Браузер запускается с прокси (headless=false). Открывается store.supercell.com.",
        )
        logger.info(f"Запуск браузера (headless=false){' с прокси' if use_proxy else ' без прокси'}...")
        await browser.start(use_proxy=use_proxy)
        result["proxy_used"] = browser.current_proxy is not None
        if browser.current_proxy:
            result["proxy_server"] = browser.current_proxy.get("server")

        logger.info("Переход на store.supercell.com...")
        store_url = "https://store.supercell.com"
        goto_ok = False
        # С прокси: сначала "commit" (меньше данных = реже ERR_CONNECTION_RESET), потом строже
        for attempt in range(1, 6):
            try:
                if attempt <= 2:
                    wait_until = "commit"  # быстрее, меньше шанс обрыва по прокси
                elif attempt <= 4:
                    wait_until = "domcontentloaded"
                else:
                    wait_until = "load"
                timeout_ms = 150000  # 2.5 мин через прокси
                await browser.page.goto(store_url, wait_until=wait_until, timeout=timeout_ms)
                goto_ok = True
                logger.info(f"Store загружен с попытки {attempt}")
                break
            except Exception as e:
                err_str = str(e).lower()
                logger.warning(f"Попытка {attempt}/5 перехода на store: {e}")
                if attempt < 5:
                    delay = 4 if "err_connection_reset" in err_str or "connection" in err_str else 3
                    await asyncio.sleep(delay)
                else:
                    hint = ""
                    if "err_timed_out" in err_str or "timeout" in err_str:
                        hint = " Увеличьте таймаут или проверьте прокси в .env (PROXY_ENABLED / BRIGHTDATA_*)."
                    elif "err_name_not_resolved" in err_str:
                        hint = " Проверьте DNS или прокси в .env."
                    elif "err_tunnel_connection_failed" in err_str:
                        hint = " Туннель прокси не установился. Запустите: python scripts/test_novada_connection.py. В .env поставьте NOVADA_PROXY_HOST=super.novada.pro"
                    elif "err_connection_reset" in err_str or "connection" in err_str:
                        hint = " Прокси обрывает соединение — попробуйте NOVADA_PROXY_HOST=super.novada.pro или PROXY_IGNORE_HTTPS_ERRORS=true в .env."
                    raise RuntimeError(f"Не удалось открыть {store_url} после 5 попыток.{hint}") from e
        if not goto_ok:
            return result
        await browser.page.wait_for_timeout(2000)
        await _accept_cookies(browser)
        await browser.human_like_delay(1000, 2000)

        # Подстановка 2Captcha при переходе на страницу входа (чтобы при ручном нажатии Log in капча уже была решена)
        _setup_2captcha_on_login_page(browser)

        # Шаг 2: Ручной вход в аккаунт
        print_step(
            2,
            "Ручной вход в аккаунт",
            "Войди в аккаунт в открытом браузере (логин + код верификации).\nЗатем нажми Enter в консоли — начнётся автоматическая покупка.",
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: input())

        await _accept_cookies(browser)
        await browser.human_like_delay(1000, 1500)

        # Шаг 3–5: Тот же путь, что в purchase_demo (API): магазин → товар → корзина → Checkout
        print_step(
            3,
            "Покупка после входа (как в purchase_demo)",
            f"Переход в магазин {game} → поиск «{product_name}» → Buy → проверка корзины и количества → Checkout.",
        )
        purchase_result = await run_purchase_flow_after_login(
            browser, game, product_name, session_id="manual_login"
        )
        result["added_to_cart"] = purchase_result.get("added_to_cart", False)
        result["checkout_opened"] = purchase_result.get("checkout_opened", False)
        result["url"] = purchase_result.get("url")
        result["message"] = purchase_result.get("message", "")
        result["screenshot"] = purchase_result.get("screenshot")

        if purchase_result.get("error"):
            result["error"] = purchase_result["error"]
        if not result["checkout_opened"]:
            result["error"] = result["error"] or "Окно Checkout не открылось."
            result["message"] = result["message"] or "Товар добавлен в корзину, но кнопка Checkout не найдена."
            return result

        result["checkout_screenshot"] = f"checkout_{product_name.replace(' ', '_')}.png"

        # Шаг 6: Оплата через Google Pay
        print_step(
            6,
            "Оплата через Google Pay",
            "Выбор вкладки G Pay в FastSpring, кнопка «Place Your Order», подтверждение в popup Google.",
        )
        gpay_result = {}
        if getattr(settings, "GOOGLE_PAY_ENABLED", False):
            email = google_email or getattr(settings, "GOOGLE_EMAIL", "") or ""
            app_password = getattr(settings, "GOOGLE_APP_PASSWORD", "") or ""
            if email and app_password:
                timeout_sec = payment_timeout or getattr(settings, "PAYMENT_TIMEOUT", 300)
                logger.info("Оплата через Google Pay...")
                gpay_result = await handle_google_pay(
                    browser=browser,
                    email=email,
                    app_password=app_password,
                    payment_timeout=timeout_sec,
                    product_name=product_name,
                )
                result["payment"] = {
                    "google_pay_clicked": gpay_result.get("google_pay_clicked", False),
                    "payment_confirmed": gpay_result.get("payment_confirmed", False),
                    "payment_verified": gpay_result.get("payment_verified", False),
                    "success": gpay_result.get("success", False),
                    "error": gpay_result.get("error"),
                }
            else:
                result["error"] = "Google Pay включён, но GOOGLE_EMAIL или GOOGLE_APP_PASSWORD не заданы."
        else:
            logger.info("Google Pay отключён (GOOGLE_PAY_ENABLED=false).")

        result["success"] = result["added_to_cart"] and result["checkout_opened"] and (
            not getattr(settings, "GOOGLE_PAY_ENABLED", False) or result["payment"].get("success", False)
        )
        return result

    except Exception as e:
        logger.exception("Ошибка демо")
        result["error"] = str(e)
        try:
            if browser.page:
                await browser.take_screenshot("manual_login_demo_error.png")
        except Exception:
            pass
        return result

    finally:
        # Всегда закрываем браузер и соединение, иначе при выходе — pending tasks и ValueError в transport
        try:
            video_path = await browser.close()
            if video_path:
                result["video"] = video_path
        except Exception as e:
            logger.debug(f"Ошибка при закрытии браузера: {e}")


def main():
    args = parse_args()
    payment_timeout = args.timeout if args.timeout is not None else getattr(settings, "PAYMENT_TIMEOUT", 300)

    # Заголовок и проверка прокси — как в purchase_demo.py
    print("=" * 60)
    print("ДЕМОНСТРАЦИЯ ПОКУПКИ ТОВАРА (ручной вход в аккаунт)")
    print("=" * 60)
    print(f"\nИгра: {args.game}")
    print(f"Товар: {args.product}")
    print("\nПроцесс (без автоматической авторизации, путь покупки как в purchase_demo):")
    print("  1. Запуск браузера с прокси, открытие store.supercell.com")
    print("  2. Ты вручную входишь в аккаунт в браузере")
    print("  3. Покупка: магазин игры -> товар \"" + args.product + "\" -> Buy -> корзина (проверка количества) -> Checkout")
    print("  4. Оплата через Google Pay")
    check_proxy_status()
    print()

    if sys.platform == "win32":
        def _run():
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    run_demo(
                        game=args.game,
                        product_name=args.product,
                        google_email=args.google_email or "",
                        payment_timeout=payment_timeout,
                        use_proxy=True,
                    )
                )
            finally:
                loop.close()

        result = _run()
    else:
        result = asyncio.run(
            run_demo(
                game=args.game,
                product_name=args.product,
                google_email=args.google_email or "",
                payment_timeout=payment_timeout,
                use_proxy=True,
            )
        )

    # Вывод результата в формате purchase_demo.py
    if result.get("success"):
        print("✅ Процесс завершён!")
    else:
        print("❌ Процесс завершён с ошибкой.")
    print(f"   Успех: {result.get('success')}")
    print(f"   Товар добавлен в корзину: {result.get('added_to_cart')}")
    print(f"   Окно оформления заказа открыто: {result.get('checkout_opened', False)}")
    if result.get("message"):
        print(f"   Сообщение: {result['message']}")
    if result.get("url"):
        print(f"   URL: {result['url']}")

    payment = result.get("payment") or {}
    if result.get("checkout_opened") and (payment.get("success") is not None or payment.get("error")):
        print(f"\n   💳 Google Pay:")
        print(f"      Успех: {payment.get('success')}")
        print(f"      Кнопка нажата: {payment.get('google_pay_clicked')}")
        print(f"      Оплата подтверждена: {payment.get('payment_confirmed')}")
        print(f"      Успех верифицирован: {payment.get('payment_verified')}")
        if payment.get("error"):
            print(f"      Ошибка: {payment.get('error')}")

    if result.get("video"):
        print(f"   Видео сессии: {result['video']}")
    if result.get("checkout_screenshot"):
        print(f"   Скриншот checkout: {result['checkout_screenshot']}")
    if result.get("screenshot"):
        print(f"   Скриншот: {result['screenshot']}")
    if "proxy_used" in result:
        print(f"\n   Прокси использовался: {result.get('proxy_used')}")
        if result.get("proxy_server"):
            print(f"   Прокси-сервер: {result['proxy_server']}")
    if result.get("error") and not payment.get("error"):
        print(f"\n   Ошибка: {result['error']}")

    print("\n" + "=" * 60)
    if result.get("success"):
        print("✅ Демонстрация завершена успешно!")
        print("   Скриншоты: screenshots/")
        if result.get("video"):
            print(f"   Видео: {result['video']}")
    else:
        print("❌ Демонстрация завершена с ошибкой")
        print("   Проверьте логи: logs/autosupercell.log")
        print("   Скриншоты ошибки: screenshots/")
    print("=" * 60)

    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()

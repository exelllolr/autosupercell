#!/usr/bin/env python3
"""
Диагностический скрипт: открыть store → checkout → G Pay → дождаться popup →
сделать скриншот + dump frames/URL в лог, без клика по кнопке «Оплатить».

Использование:
  python scripts/debug_gpay_popup.py
  python scripts/debug_gpay_popup.py --checkout-url "https://pay.fastspring.com/..."
  python scripts/debug_gpay_popup.py --game clash-royale --product "80 Gems"

Запуск на сервере (Docker): тот же, внутри контейнера. Скриншоты в ./screenshots/
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

os.environ.setdefault("BROWSER_HEADLESS", "false")

from loguru import logger

from app.config import settings
from app.core.browser_automation import BrowserAutomation
from app.core.google_pay import select_gpay_tab_and_pay
from app.api.store_routes import run_purchase_flow_after_login
from app.api.supercell_auth_routes import _accept_cookies


async def _dump_popup_diagnostics(popup_page, prefix: str = "gpay_popup") -> None:
    """Скриншот + dump URL, frames, body text в лог."""
    try:
        url = popup_page.url or ""
        logger.info("[%s] URL: %s", prefix, url[:200])
        frames = getattr(popup_page, "frames", [])
        logger.info("[%s] Frames: %s", prefix, len(frames))
        for i, f in enumerate(frames):
            try:
                logger.info("[%s] Frame[%s] url=%s", prefix, i, (getattr(f, "url", "") or "")[:120])
            except Exception:
                pass
        body_text = await popup_page.evaluate("() => document.body.innerText")
        preview = (body_text or "")[:500]
        logger.info("[%s] Body text preview: %s", prefix, repr(preview))
        if "this browser" in (body_text or "").lower() or "couldn't sign" in (body_text or "").lower():
            logger.warning("[%s] Обнаружена возможная блокировка Google!", prefix)
        os.makedirs("screenshots", exist_ok=True)
        path = f"screenshots/{prefix}_debug.png"
        await popup_page.screenshot(path=path)
        logger.info("[%s] Скриншот сохранён: %s", prefix, path)
    except Exception as e:
        logger.error("[%s] Ошибка dump: %s", prefix, e)


async def run_debug(
    game: str = "clash-royale",
    product_name: str = "80 Gems",
    checkout_url: str = "",
) -> dict:
    browser = BrowserAutomation()
    result = {"success": False, "popup_seen": False, "screenshot": None}

    try:
        await browser.start()
        page = browser.page
        if not page:
            result["error"] = "Страница не инициализирована"
            return result

        if checkout_url:
            logger.info("Переход на checkout URL: %s", checkout_url[:80])
            await page.goto(checkout_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)
        else:
            logger.info("Переход на store.supercell.com...")
            await page.goto("https://store.supercell.com", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            await _accept_cookies(browser)
            print("\n>>> Войди в аккаунт вручную в браузере, добавь товар в корзину и открой Checkout.")
            print(">>> Когда будешь на странице Checkout (FastSpring/Appcharge), нажми Enter здесь.")
            input()
            await _accept_cookies(browser)
            await page.wait_for_timeout(2000)
            if not checkout_url:
                logger.info("Запуск purchase flow для перехода в checkout...")
                purchase_result = await run_purchase_flow_after_login(
                    browser, game, product_name, session_id="debug_gpay"
                )
                if not purchase_result.get("checkout_opened"):
                    result["error"] = purchase_result.get("message") or "Checkout не открылся"
                    return result

        logger.info("Клик по вкладке G Pay и кнопке Place Your Order...")
        async with page.context.expect_page(timeout=120000) as popup_info:
            clicked = await select_gpay_tab_and_pay(page, timeout_ms=90000)
        if clicked:
            popup_page = await popup_info.value
            result["popup_seen"] = True
            logger.info("Popup открылся: %s", popup_page.url[:100])
            await popup_page.wait_for_load_state("domcontentloaded", timeout=30000)
            await popup_page.wait_for_timeout(5000)
            await _dump_popup_diagnostics(popup_page, "gpay_popup_debug")
            result["screenshot"] = "screenshots/gpay_popup_debug.png"
            result["success"] = True
        else:
            result["error"] = "Не удалось кликнуть G Pay или кнопка Place Your Order не найдена"

    except Exception as e:
        logger.exception("Ошибка debug_gpay_popup")
        result["error"] = str(e)
    finally:
        await browser.close()

    return result


def main():
    parser = argparse.ArgumentParser(description="Диагностика Google Pay popup")
    parser.add_argument("--game", default="clash-royale")
    parser.add_argument("--product", default="80 Gems")
    parser.add_argument("--checkout-url", default="", help="Прямой URL страницы checkout")
    args = parser.parse_args()

    print("=" * 60)
    print("DEBUG: Google Pay Popup")
    print("=" * 60)
    print("Цель: открыть popup Google Pay и сделать скриншот + dump без клика по кнопке.")
    print()

    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            run_debug(
                game=args.game,
                product_name=args.product,
                checkout_url=args.checkout_url,
            )
        )
    else:
        result = asyncio.run(
            run_debug(
                game=args.game,
                product_name=args.product,
                checkout_url=args.checkout_url,
            )
        )

    print()
    print("Результат:", result)
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())

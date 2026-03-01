"""
Демо покупки через GoLogin.
Запускает браузер через GoLogin, переходит на store, при необходимости выполняет login_supercell (email + код).
Запуск из корня проекта: python -m gologin_runner.purchase
Переменные окружения: GOLOGIN_API_TOKEN, GOLOGIN_PROFILE_ID; для входа — передать email (и опционально код) в коде или через .env.
"""

import asyncio
import os
from loguru import logger

from app.core.browser_automation import BrowserAutomation


async def main() -> None:
    automation = BrowserAutomation()
    try:
        await automation.start()
        logger.info("Браузер запущен (GoLogin при наличии настроек)")

        await automation.navigate_to_supercell_login()
        await automation.take_screenshot("gologin_before_login.png")

        # Опционально: авторизация, если задан email (например через env SUPERCELL_DEMO_EMAIL)
        email = os.environ.get("SUPERCELL_DEMO_EMAIL", "").strip()
        code = os.environ.get("SUPERCELL_DEMO_CODE", "").strip() or None
        if email:
            result = await automation.login_supercell(email, verification_code=code)
            logger.info(f"Результат авторизации: {result.get('status', 'unknown')}")
            await automation.take_screenshot("gologin_after_login.png")
        else:
            logger.info("SUPERCELL_DEMO_EMAIL не задан — пропуск авторизации, только скриншот главной")

    finally:
        await automation.close()


if __name__ == "__main__":
    asyncio.run(main())

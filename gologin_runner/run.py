"""
Главный скрипт запуска через GoLogin.
Запускает браузер (GoLogin при наличии GOLOGIN_* в .env), переходит на Supercell Store, делает скриншот, закрывает.
Запуск из корня проекта: python -m gologin_runner.run
"""

import asyncio
from loguru import logger

from app.core.browser_automation import BrowserAutomation


async def main() -> None:
    automation = BrowserAutomation()
    try:
        await automation.start()
        logger.info("Браузер запущен, переход на Supercell Store...")
        await automation.navigate_to_supercell_login()
        path = await automation.take_screenshot("gologin_store.png")
        logger.info(f"Скриншот сохранён: {path}")
    finally:
        await automation.close()


if __name__ == "__main__":
    asyncio.run(main())

"""
Решение reCAPTCHA Enterprise через 2Captcha (опционально).
Если CAPTCHA_2CAPTCHA_API_KEY не задан — решения не выполняются.
"""
import asyncio
from typing import Optional
from loguru import logger

# Site key Supercell (из скрипта accounts.supercell.com)
SUPERCELL_RECAPTCHA_SITEKEY = "6Leb7KMpAAAAAAm20DGNdW_O7fuW4hECp4PpE6cI"
SUPERCELL_LOGIN_URL = "https://accounts.supercell.com/login"


async def solve_recaptcha_enterprise(
    api_key: str,
    page_url: str = SUPERCELL_LOGIN_URL,
    sitekey: str = SUPERCELL_RECAPTCHA_SITEKEY,
    timeout: int = 120,
) -> Optional[str]:
    """
    Получить токен reCAPTCHA Enterprise через 2Captcha.
    Возвращает токен или None при ошибке.
    """
    try:
        from twocaptcha import TwoCaptcha
    except ImportError:
        logger.warning("2captcha-python не установлен. pip install 2captcha-python")
        return None

    def _solve():
        solver = TwoCaptcha(api_key)
        result = solver.recaptcha(
            sitekey=sitekey,
            url=page_url,
            enterprise=1,
            invisible=1,
        )
        if result is None:
            return None
        if isinstance(result, dict):
            return result.get("code")
        if isinstance(result, str):
            return result
        return getattr(result, "code", None) or str(result)

    try:
        loop = asyncio.get_event_loop()
        token = await asyncio.wait_for(
            loop.run_in_executor(None, _solve),
            timeout=timeout,
        )
        if token:
            logger.info("reCAPTCHA Enterprise: токен получен через 2Captcha")
        return token
    except asyncio.TimeoutError:
        logger.warning("2Captcha: таймаут ожидания токена")
        return None
    except Exception as e:
        logger.warning("2Captcha: ошибка получения токена: %s", e)
        return None

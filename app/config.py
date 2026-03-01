"""Конфигурация приложения."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Настройки приложения."""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    BROWSER_HEADLESS: bool = True
    BROWSER_USE_CHROME: bool = False
    BROWSER_WARMUP: bool = True
    BROWSER_USE_PERSISTENT_PROFILE: bool = True
    BROWSER_PROFILE_DIR: str = "browser_profile"
    # True = использовать профиль установленного Chrome (тот же, где ты заходишь вручную)
    # ВАЖНО: перед запуском закрой Chrome полностью
    BROWSER_USE_SYSTEM_PROFILE: bool = False
    BROWSER_WARMUP_VISIT_SUPERCELL: bool = True
    BROWSER_USE_STEALTH_PLUGIN: bool = True
    # True = использовать Patchright (undetected Playwright). Нужно: pip install patchright && patchright install chrome
    # Для входа в Google Pay рекомендуется: BROWSER_USE_PATCHRIGHT=True, BROWSER_HEADLESS=False, BROWSER_USE_CHROME=True
    BROWSER_USE_PATCHRIGHT: bool = False
    # Записывать видео сессии (только при обычном контексте; при persistent профиле недоступно)
    BROWSER_RECORD_VIDEO: bool = True
    # Режим инкогнито (может помочь при блокировках)
    BROWSER_INCOGNITO: bool = False

    # GoLogin anti-detect browser (alternative to Patchright)
    GOLOGIN_API_TOKEN: str = ""
    GOLOGIN_PROFILE_ID: str = ""

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # AI Providers
    AI_PROVIDER: str = "openai"  # openai, claude, gemini
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    # Supercell Store URLs
    SUPERCELL_STORE_URL: str = "https://store.supercell.com"
    CLASH_ROYALE_STORE_URL: str = "https://store.supercell.com/clash-royale"
    BRAWL_STARS_STORE_URL: str = "https://store.supercell.com/brawl-stars"

    # Proxy
    PROXY_ENABLED: bool = True
    PROXY_ROTATION_ENABLED: bool = True
    PROXY_LIST_FILE: str = "proxies.txt"
    PROXY_USE_FIRST_ONLY: bool = False

    # Novada proxy (резидентные/датацентр прокси)
    NOVADA_ENABLED: bool = False
    NOVADA_ROTATING: bool = False  # True = Rotating Session (gateway сам ротирует IP)
    NOVADA_USERNAME: str = ""
    NOVADA_API_KEY: str = ""
    NOVADA_ZONE: str = "res"   # res | dcp
    NOVADA_REGION: str = "us"  # Страна: us, gb, de и т.д. (2-letter ISO или код Novada)
    NOVADA_STATE: str = ""     # Штат/регион: oregon, california (пусто = любой)
    NOVADA_CITY: str = ""      # Город: portland (пусто = любой). Список: country_map_en.xlsx на novada.com
    NOVADA_PROXY_HOST: str = "super.novada.pro"
    NOVADA_PROXY_PORT: int = 7777
    NOVADA_STICKY_MINUTES: int = 0  # 0 = rotating; 5–120 = sticky session (один IP на N минут)

    # reCAPTCHA solving (2Captcha) — опционально для обхода блокировки Supercell
    CAPTCHA_2CAPTCHA_API_KEY: str = ""
    # Задержка (сек) перед нажатием LOG IN на accounts.supercell.com — снижает «unusual activity»
    SUPERCELL_LOGIN_DELAY_BEFORE_SUBMIT: int = 5
    # Задержка (сек) после нажатия LOG IN перед проверкой страницы — даёт время загрузиться форме кода или странице блокировки
    SUPERCELL_LOGIN_DELAY_AFTER_SUBMIT: int = 8

    # Payment — Google Pay
    GOOGLE_PAY_ENABLED: bool = True
    PAYMENT_TIMEOUT: int = 420  # секунд на вход в Google и подтверждение оплаты (7 мин)
    # Google аккаунт для оплаты (App Password: myaccount.google.com/apppasswords)
    GOOGLE_EMAIL: str = ""
    GOOGLE_APP_PASSWORD: str = ""
    # Резервные коды Google (8-значная верификация после пароля). Один код или несколько через запятую; пробелы игнорируются. Пример: 5519 2680 или 55192680,12345678
    GOOGLE_BACKUP_CODES: str = ""

    # External Services
    PLATI_API_KEY: str = ""
    PLATI_API_URL: str = "https://plati.io/api"

    KUPIKOD_WEBHOOK_SECRET: str = ""
    KUPIKOD_API_URL: str = "https://kupikod.ru/api"

    FUNPAY_API_KEY: str = ""
    FUNPAY_API_URL: str = "https://funpay.com/api"

    AVITO_API_KEY: str = ""
    AVITO_API_URL: str = "https://api.avito.ru"

    # Security
    ENCRYPTION_KEY: str = ""
    SESSION_TIMEOUT: int = 3600

    # Monitoring
    PROMETHEUS_ENABLED: bool = True
    METRICS_PORT: int = 9090

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/autosupercell.log"

    # Order Configuration
    MAX_ORDER_TTL: int = 600
    TARGET_ORDER_TTL: int = 120
    MAX_RETRIES: int = 3

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

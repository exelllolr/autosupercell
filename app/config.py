"""Конфигурация приложения."""

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения."""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # Security — API-ключ для защиты всех эндпоинтов (кроме /health и /).
    # Если пусто — авторизация отключена (не рекомендуется в продакшене).
    # Задайте в .env: API_SECRET_KEY=ваш_секретный_ключ
    # Клиент передаёт его в заголовке: X-API-Key: <ключ>
    API_SECRET_KEY: str = ""

    # CORS — список разрешённых источников через запятую.
    # В продакшене укажите конкретные домены: "https://yourdomain.com,https://app.yourdomain.com"
    # Оставьте "*" только если API доступен исключительно внутри приватной сети.
    CORS_ORIGINS: str = "*"

    # Browser
    BROWSER_HEADLESS: bool = True
    BROWSER_USE_CHROME: bool = False
    BROWSER_WARMUP: bool = True
    BROWSER_USE_PERSISTENT_PROFILE: bool = True
    BROWSER_PROFILE_DIR: str = "browser_profile"

    # ИСПРАВЛЕНО (было True): системный профиль Chrome (LOCALAPPDATA) недоступен
    # в Docker и на серверах без GUI. Принудительно отключён по умолчанию.
    # Включайте только при локальной разработке с установленным Chrome + Browsec VPN.
    BROWSER_USE_SYSTEM_PROFILE: bool = False

    BROWSER_WARMUP_VISIT_SUPERCELL: bool = True
    BROWSER_USE_STEALTH_PLUGIN: bool = True

    # True = использовать Patchright (undetected Playwright).
    # Нужно: pip install patchright && patchright install chrome
    # Для входа в Google Pay рекомендуется: BROWSER_USE_PATCHRIGHT=True,
    # BROWSER_HEADLESS=False, BROWSER_USE_CHROME=True
    BROWSER_USE_PATCHRIGHT: bool = False

    # Записывать видео сессии (только при обычном контексте;
    # при persistent профиле в headed режиме недоступно).
    BROWSER_RECORD_VIDEO: bool = True

    # Режим инкогнито (может помочь при блокировках)
    BROWSER_INCOGNITO: bool = False

    # Расширение US Region для store/accounts.supercell.com
    BROWSER_USE_US_EXTENSION: bool = False
    BROWSER_EXTENSION_PATH: str = "browser_extensions/us_region"

    # ИСПРАВЛЕНО (было True): Browsec VPN требует установленного расширения в Chrome
    # и системного профиля — недоступно в Docker/сервере без GUI.
    # Включайте только при локальной разработке с Browsec в Chrome.
    BROWSER_USE_BROWSEC_VPN: bool = False
    BROWSER_BROWSEC_VPN_REGION: str = "US"

    # GoLogin anti-detect browser
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
    
    # Claude specific settings
    CLAUDE_MODEL: str = "claude-3-5-sonnet-20241022"
    CLAUDE_MAX_TOKENS: int = 1024
    CLAUDE_TIMEOUT: int = 30
    CLAUDE_ENABLE_CACHING: bool = True

    # Supercell Store URLs
    # ВАЖНО: правильные URL без дефиса (/clashroyale, /brawlstars)
    # Старые URL с дефисом (/clash-royale, /brawl-stars) ведут на 404
    SUPERCELL_STORE_URL: str = "https://store.supercell.com"
    CLASH_ROYALE_STORE_URL: str = "https://store.supercell.com/clashroyale"
    BRAWL_STARS_STORE_URL: str = "https://store.supercell.com/brawlstars"

    # Proxy
    PROXY_ENABLED: bool = True
    PROXY_ROTATION_ENABLED: bool = True
    PROXY_LIST_FILE: str = "proxies.txt"
    PROXY_USE_FIRST_ONLY: bool = False
    # False = при провале всех прокси не переходить на реальный IP.
    # True = один раз попробовать без прокси.
    PROXY_FALLBACK_NO_PROXY: bool = False
    # True = прокси только в браузере (не в системных HTTP_PROXY)
    PROXY_BROWSER_ONLY: bool = True
    # True = игнорировать ошибки сертификата при прокси
    PROXY_IGNORE_HTTPS_ERRORS: bool = False
    # Обход прокси для доменов Google (логин, G Pay).
    # Пусто = не обходить.
    PROXY_BYPASS_GOOGLE: str = (
        "*.google.com,*.googleapis.com,*.gstatic.com,*.youtube.com"
    )

    # Novada proxy (резидентные/датацентр прокси)
    NOVADA_ENABLED: bool = True
    NOVADA_ONLY: bool = False  # True = только Novada, не грузить прокси из файла
    NOVADA_ROTATING: bool = False  # True = Rotating Session (gateway сам ротирует IP)
    NOVADA_USERNAME: str = ""
    NOVADA_API_KEY: str = ""
    NOVADA_ZONE: str = "res"  # res | dcp
    NOVADA_REGION: str = "us"  # Страна: us, gb, de и т.д. (2-letter ISO)
    NOVADA_STATE: str = ""  # Штат: oregon, california (пусто = любой)
    NOVADA_CITY: str = ""  # Город: portland (пусто = любой)
    NOVADA_PROXY_HOST: str = "super.novada.pro"
    NOVADA_PROXY_PORT: int = 7777
    NOVADA_STICKY_MINUTES: int = 0  # 0 = rotating; 5–120 = sticky session

    # Bright Data proxy
    BRIGHTDATA_ENABLED: bool = False
    BRIGHTDATA_ONLY: bool = False  # True = только Bright Data, не грузить proxies.txt
    BRIGHTDATA_HOST: str = "brd.superproxy.io"
    BRIGHTDATA_PORT: int = 33335
    BRIGHTDATA_USERNAME: str = ""
    BRIGHTDATA_PASSWORD: str = ""

    # reCAPTCHA solving (2Captcha) — опционально для обхода блокировки Supercell
    CAPTCHA_2CAPTCHA_API_KEY: str = ""

    # Payment — Google Pay
    GOOGLE_PAY_ENABLED: bool = True
    PAYMENT_TIMEOUT: int = 300  # секунд на вход в Google и подтверждение оплаты
    # Ожидание загрузки popup pay.google.com с кнопкой «Оплатить» (секунды).
    # На сервере с медленной сетью/прокси увеличьте до 30–40.
    GOOGLE_PAY_POPUP_LOAD_WAIT_SEC: int = 25
    # Google аккаунт для оплаты (App Password: myaccount.google.com/apppasswords)
    GOOGLE_EMAIL: str = ""
    GOOGLE_APP_PASSWORD: str = ""
    # Резервные коды Google (8-значная верификация после пароля).
    # Один код или несколько через запятую; пробелы игнорируются.
    # Пример: 5519 2680 или 55192680,12345678
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
    
    # Browser Diagnostics (network and console logging)
    BROWSER_NETWORK_LOG: bool = True
    BROWSER_CONSOLE_LOG: bool = True

    # Order Configuration
    MAX_ORDER_TTL: int = 600
    TARGET_ORDER_TTL: int = 120
    MAX_RETRIES: int = 3

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

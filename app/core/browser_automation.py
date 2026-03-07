"""Браузерная автоматизация на Patchright (undetected Playwright)."""

import asyncio
import random
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from app.config import settings
from app.core.proxy_manager import proxy_manager

# Типы и драйвер: Patchright совместим с API Playwright
try:
    from patchright.async_api import Browser, BrowserContext, Page, async_playwright
except ImportError:
    raise ImportError(
        "Установите Patchright: pip install patchright && patchright install chrome"
    )


def _get_playwright():
    """Возвращает (async_playwright, use_patchright_recommended).
    use_patchright_recommended=True — только патчи Patchright, без наших CDP/stealth.
    """
    use_recommended = getattr(settings, "BROWSER_USE_PATCHRIGHT", False)
    if use_recommended:
        logger.info("Режим Patchright: рекомендуемый запуск (без доп. stealth)")
    return async_playwright, use_recommended


# Реалистичные User-Agents для ротации
USER_AGENTS = [
    # Windows 10 Chrome (самый популярный)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Windows 11 Chrome
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

# Реалистичные viewport размеры
VIEWPORTS = [
    {"width": 1920, "height": 1080},  # Full HD
    {"width": 1680, "height": 1050},  # WSXGA+
    {"width": 1600, "height": 900},  # HD+
    {"width": 1536, "height": 864},  # Common laptop
    {"width": 1440, "height": 900},  # MacBook
]

# Реалистичные языки
LANGUAGES = [
    ["en-US", "en"],
    ["en-US", "en", "ru"],
    ["en-GB", "en"],
]


class BrowserAutomation:
    """Управление браузером для автоматизации покупок."""

    def __init__(self):
        """Инициализация браузерной автоматизации."""
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.current_user_agent: Optional[str] = None
        self.current_viewport: Optional[Dict] = None
        self.current_proxy: Optional[Dict] = (
            None  # для mark_proxy_failed при ошибке навигации
        )

    async def start(
        self,
        retry_proxy: bool = True,
        max_proxy_retries: int = 3,
        use_proxy: Optional[bool] = None,
    ) -> None:
        """
        Запуск браузера с улучшенным stealth режимом.

        Args:
            retry_proxy: Попробовать другой прокси при ошибке (по умолчанию True)
            max_proxy_retries: Максимальное количество попыток с разными прокси
            use_proxy: True = использовать прокси из настроек, False = без прокси, None = по умолчанию (из PROXY_ENABLED)
        """
        proxy_attempts = 0
        last_error = None

        while proxy_attempts < max_proxy_retries:
            try:
                async_playwright, use_patchright = _get_playwright()
                self.playwright = await async_playwright().start()
                if use_proxy is False:
                    proxy = None
                else:
                    proxy = proxy_manager.get_proxy()
                self.current_proxy = proxy

                if proxy:
                    server = proxy.get("server", "unknown")
                    username = proxy.get("username", "")
                    logger.info(
                        f"Попытка {proxy_attempts + 1}/{max_proxy_retries}: "
                        f"Использование прокси {server} (user: {username})"
                    )
                else:
                    logger.info("Прокси не используется (отключен или не настроен)")

                # ВАЖНО: Рандомизация User-Agent и Viewport ДО создания браузера
                self.current_viewport = random.choice(VIEWPORTS)
                self.current_user_agent = random.choice(USER_AGENTS)
                current_languages = random.choice(LANGUAGES)

                logger.info(
                    f"Используется User-Agent: {self.current_user_agent[:50]}..."
                )
                logger.info(f"Используется Viewport: {self.current_viewport}")

                # Расширенные аргументы для обхода детекции
                # Убраны подозрительные флаги типа --disable-web-security
                browser_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--dns-prefetch-disable",
                    "--no-dns-over-https",
                    "--host-resolver-flags=default_address_family=IPv4",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",  # Требуется для Docker
                    "--disable-setuid-sandbox",  # Требуется для Docker
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials",
                    "--disable-infobars",
                    f"--window-size={self.current_viewport['width']},{self.current_viewport['height']}",
                    "--start-maximized",
                    "--disable-extensions",
                    "--disable-plugins-discovery",
                    "--disable-default-apps",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-features=TranslateUI",
                    "--disable-ipc-flooding-protection",
                    "--exclude-switches=enable-automation",  # Важно: скрывает автоматизацию
                    "--enable-features=NetworkService,NetworkServiceInProcess",
                    "--disable-component-extensions-with-background-pages",
                ]
                if getattr(settings, "BROWSER_INCOGNITO", False):
                    browser_args.append("--incognito")

                # Определяем headless режим
                import os

                is_docker = (
                    os.path.exists("/.dockerenv")
                    or os.environ.get("DOCKER_CONTAINER") == "true"
                )

                # В Docker headed режим возможен только при наличии виртуального дисплея (Xvfb).
                # Если задан DISPLAY (например :99 от Xvfb) — разрешаем BROWSER_HEADLESS=false.
                # Без DISPLAY в Docker принудительно включаем headless.
                #
                # Зачем это нужно:
                #   Cloudflare Turnstile на accounts.supercell.com/login блокирует headless Chrome —
                #   форма входа не рендерится (email input не появляется в DOM).
                #   Xvfb + headed Chrome обходит это: Turnstile не отличает его от реального браузера.
                if is_docker:
                    display_var = os.environ.get("DISPLAY", "").strip()
                    has_xvfb_display = bool(display_var)
                    requested_headless = getattr(settings, "BROWSER_HEADLESS", True)

                    if has_xvfb_display and not requested_headless:
                        # Xvfb запущен + явно задан BROWSER_HEADLESS=false → headed Chrome
                        headless_mode = False
                        logger.info(
                            "Docker + Xvfb: headed режим Chrome включён "
                            "(DISPLAY=%s, BROWSER_HEADLESS=false). "
                            "Cloudflare Turnstile будет проходить корректно.",
                            display_var,
                        )
                    elif has_xvfb_display and requested_headless:
                        # Xvfb есть, но headless=true — оставляем headless (пользователь сам решил)
                        headless_mode = True
                        logger.info(
                            "Docker + Xvfb: DISPLAY=%s, но BROWSER_HEADLESS=true → headless режим. "
                            "Если возникает ошибка Turnstile — установите BROWSER_HEADLESS=false в .env.",
                            display_var,
                        )
                    else:
                        # Нет Xvfb → принудительно headless
                        headless_mode = True
                        if not requested_headless:
                            logger.warning(
                                "Docker: BROWSER_HEADLESS=false проигнорировано — DISPLAY не задан "
                                "(Xvfb не запущен). Принудительно headless режим. "
                                "Для headed режима используйте docker-compose с DISPLAY=:99 "
                                "и CMD scripts/start_with_xvfb.sh."
                            )
                else:
                    headless_mode = (
                        getattr(settings, "BROWSER_HEADLESS", True)
                        if hasattr(settings, "BROWSER_HEADLESS")
                        else not settings.DEBUG
                    )
                use_chrome = getattr(settings, "BROWSER_USE_CHROME", False)

                # В headed режиме убираем часть флагов, чтобы Chrome не выглядел подозрительно.
                # НО: в Docker через Xvfb оставляем --no-sandbox и --disable-dev-shm-usage —
                # они нужны для стабильной работы Chrome внутри контейнера.
                if not headless_mode:
                    _docker_only_flags = (
                        "--disable-extensions",
                        "--disable-plugins-discovery",
                        "--disable-default-apps",
                        "--disable-component-extensions-with-background-pages",
                    )
                    if not is_docker:
                        # Локально (не Docker) — убираем также sandbox-флаги
                        _docker_only_flags = _docker_only_flags + (
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-dev-shm-usage",
                        )
                    browser_args = [
                        a for a in browser_args if a not in _docker_only_flags
                    ]
                    if is_docker:
                        logger.info(
                            "Headed режим (Docker+Xvfb): убраны флаги расширений/плагинов, "
                            "оставлены --no-sandbox и --disable-dev-shm-usage для стабильности в контейнере."
                        )
                    else:
                        logger.info(
                            "Headed режим (локально): убраны Docker-специфичные флаги для лучшей имитации."
                        )

                use_persistent = getattr(
                    settings, "BROWSER_USE_PERSISTENT_PROFILE", True
                )
                use_system_profile = getattr(
                    settings, "BROWSER_USE_SYSTEM_PROFILE", False
                )

                # ИСПРАВЛЕНО: системный профиль Chrome (LOCALAPPDATA) недоступен
                # в Docker — нет GUI и нет пути %LOCALAPPDATA%. Принудительно отключаем.
                if is_docker and use_system_profile:
                    logger.warning(
                        "Docker: системный профиль Chrome (BROWSER_USE_SYSTEM_PROFILE) "
                        "принудительно отключён — LOCALAPPDATA недоступен в контейнере."
                    )
                    use_system_profile = False

                # Предупреждение: запись видео несовместима с persistent profile
                # в headed (локальном) режиме. В headless/Docker это не проблема —
                # используется обычный контекст с поддержкой видео.
                if (
                    use_persistent
                    and not headless_mode
                    and getattr(settings, "BROWSER_RECORD_VIDEO", True)
                ):
                    logger.warning(
                        "BROWSER_RECORD_VIDEO=true несовместимо с persistent profile "
                        "в headed режиме — видео записано не будет. "
                        "Для записи видео установите BROWSER_USE_PERSISTENT_PROFILE=false."
                    )

                if use_system_profile:
                    localappdata = os.environ.get("LOCALAPPDATA", "")
                    default_chrome_user_data = (
                        os.path.join(localappdata, "Google", "Chrome", "User Data")
                        if localappdata
                        else ""
                    )
                    custom = getattr(settings, "BROWSER_PROFILE_DIR", "").strip()
                    profile_dir = (
                        Path(custom)
                        if (custom and os.path.isabs(custom))
                        else Path(default_chrome_user_data or "browser_profile")
                    )
                    logger.warning(
                        "Используется системный профиль Chrome: %s. Закрой Chrome перед запуском.",
                        profile_dir,
                    )
                else:
                    raw_profile = getattr(
                        settings, "BROWSER_PROFILE_DIR", "browser_profile"
                    )
                    profile_dir = Path(raw_profile)
                    if not profile_dir.is_absolute():
                        # Абсолютный путь — иначе Chrome выдаёт «Не удалось создать каталог данных»
                        try:
                            project_root = Path(__file__).resolve().parent.parent.parent
                        except Exception:
                            project_root = Path.cwd()
                        profile_dir = (project_root / raw_profile).resolve()
                    profile_dir.mkdir(parents=True, exist_ok=True)
                    logger.debug(f"Профиль браузера: {profile_dir}")

                # Абсолютный путь — аналогично take_screenshot: в headed+persistent режиме
                # Chromium стартует из директории профиля, относительный "videos" → FileNotFoundError.
                try:
                    _project_root_v = Path(__file__).resolve().parent.parent.parent
                except Exception:
                    _project_root_v = Path.cwd()
                video_dir = (_project_root_v / "videos").resolve()
                video_dir.mkdir(parents=True, exist_ok=True)
                first_lang = current_languages[0]
                locale = first_lang if "-" in first_lang else f"{first_lang}-US"

                proxy_enabled = getattr(settings, "PROXY_ENABLED", False)
                if proxy_enabled and proxy:
                    ctx_timezone = "America/New_York"
                    ctx_geolocation = {"latitude": 40.7128, "longitude": -74.0060}
                else:
                    ctx_timezone = None
                    ctx_geolocation = None

                ignore_https = bool(
                    proxy and getattr(settings, "PROXY_IGNORE_HTTPS_ERRORS", False)
                )
                if ignore_https:
                    logger.info(
                        "Прокси: включён обход ошибок сертификата (PROXY_IGNORE_HTTPS_ERRORS) — снижает ERR_CONNECTION_RESET"
                    )
                # Трафик к Google (логин, G Pay) — напрямую к серверам Google, не через прокси (избегаем ERR_TUNNEL_CONNECTION_FAILED)
                proxy_for_context = proxy
                if proxy:
                    bypass_google = getattr(
                        settings,
                        "PROXY_BYPASS_GOOGLE",
                        "*.google.com,*.googleapis.com,*.gstatic.com,*.youtube.com",
                    ).strip()
                    if bypass_google:
                        proxy_for_context = {**proxy, "bypass": bypass_google}
                        logger.info(
                            "Прокси: обход для доменов Google — трафик к логину/G Pay идёт напрямую к серверам Google"
                        )
                if use_patchright and use_persistent and not headless_mode:
                    # Рекомендация Patchright: минимум опций, без своего UA/headers/viewport.
                    # args для Google: отключаем детекцию автоматизации ("This browser or app may not be secure").
                    context_options = {
                        "locale": locale,
                        "color_scheme": "light",
                        "proxy": proxy_for_context,
                        "headless": headless_mode,
                        "channel": "chrome",
                        "no_viewport": True,
                        "java_script_enabled": True,
                        "accept_downloads": True,
                        "ignore_https_errors": ignore_https,
                        "bypass_csp": True,  # FastSpring/pay.fastspring.com блокирует Sentry по CSP — обход для оплаты
                        "args": [
                            "--disable-blink-features=AutomationControlled",
                            "--exclude-switches=enable-automation",
                        ],
                    }
                    if ctx_timezone:
                        context_options["timezone_id"] = ctx_timezone
                    if ctx_geolocation:
                        context_options["permissions"] = ["geolocation"]
                        context_options["geolocation"] = ctx_geolocation
                else:
                    context_options = {
                        "viewport": self.current_viewport,
                        "user_agent": self.current_user_agent,
                        "locale": locale,
                        "color_scheme": "light",
                        "device_scale_factor": random.choice([1, 1.25, 1.5]),
                        "has_touch": False,
                        "is_mobile": False,
                        "java_script_enabled": True,
                        "accept_downloads": True,
                        "ignore_https_errors": ignore_https,
                        "bypass_csp": True,  # FastSpring блокирует connect к sentry-cdn.com по CSP — без обхода оплата ломается
                        "proxy": proxy_for_context,
                        "extra_http_headers": {
                            "Accept-Language": ",".join(
                                [
                                    f"{lang};q={0.9 - i * 0.1}"
                                    for i, lang in enumerate(current_languages)
                                ]
                            ),
                        },
                    }
                    if not use_patchright:
                        context_options["args"] = browser_args
                    if ctx_timezone:
                        context_options["timezone_id"] = ctx_timezone
                    if ctx_geolocation:
                        context_options["permissions"] = ["geolocation"]
                        context_options["geolocation"] = ctx_geolocation
                    if use_chrome:
                        context_options["channel"] = "chrome"
                        logger.info(
                            "Используется установленный Chrome (меньше детекта автоматизации)"
                        )

                if use_persistent and not headless_mode:
                    context_options.pop("record_video_dir", None)
                    context_options.pop("record_video_size", None)
                    context_options["headless"] = headless_mode
                    # Запасной профиль в папке проекта (если системный недоступен)
                    try:
                        project_root = Path(__file__).resolve().parent.parent.parent
                    except Exception:
                        project_root = Path.cwd()
                    fallback_profile = (project_root / "browser_profile").resolve()
                    fallback_profile.mkdir(parents=True, exist_ok=True)

                    logger.info(f"Запуск с постоянным профилем: {profile_dir}")
                    try:
                        self.context = (
                            await self.playwright.chromium.launch_persistent_context(
                                str(profile_dir), **context_options
                            )
                        )
                        self.browser = None
                    except Exception as e:
                        err_lower = str(e).lower()
                        if use_chrome and (
                            "chrome" in err_lower or "not found" in err_lower
                        ):
                            logger.warning(
                                "Chrome недоступен для persistent context (%s), пробуем без channel",
                                e,
                            )
                            context_options_pop = context_options.pop
                            context_options_pop("channel", None)
                            try:
                                self.context = await self.playwright.chromium.launch_persistent_context(
                                    str(profile_dir), **context_options
                                )
                                self.browser = None
                            except Exception as e2:
                                if use_system_profile:
                                    logger.warning(
                                        "Системный профиль недоступен (%s). Используем browser_profile в папке проекта.",
                                        e2,
                                    )
                                    if use_chrome:
                                        context_options["channel"] = "chrome"
                                    self.context = await self.playwright.chromium.launch_persistent_context(
                                        str(fallback_profile), **context_options
                                    )
                                    self.browser = None
                                else:
                                    raise
                        elif use_system_profile:
                            logger.warning(
                                "Не удалось зайти в системный профиль Chrome (%s). "
                                "Закрой Chrome полностью или поставьте BROWSER_USE_SYSTEM_PROFILE=false. "
                                "Запуск с профилем в папке проекта.",
                                e,
                            )
                            if use_chrome:
                                context_options["channel"] = "chrome"
                            self.context = await self.playwright.chromium.launch_persistent_context(
                                str(fallback_profile), **context_options
                            )
                            self.browser = None
                        else:
                            raise
                else:
                    # Прокси задаём только на уровне context (new_context), чтобы он применялся ко всем страницам и popup
                    launch_options = {
                        "headless": headless_mode,
                    }
                    if not use_patchright:
                        launch_options["args"] = browser_args
                    else:
                        # Patchright: минимум args, но DNS-флаги нужны в Docker
                        launch_options["args"] = [
                            "--dns-prefetch-disable",
                            "--no-dns-over-https",
                            "--host-resolver-flags=default_address_family=IPv4",
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-dev-shm-usage",
                        ]
                    if use_chrome:
                        launch_options["channel"] = "chrome"
                    try:
                        self.browser = await self.playwright.chromium.launch(
                            **launch_options
                        )
                    except Exception as e:
                        if use_chrome and (
                            "chrome" in str(e).lower() or "not found" in str(e).lower()
                        ):
                            logger.warning(
                                "Chrome недоступен (%s), используем Chromium", e
                            )
                            launch_options.pop("channel", None)
                            self.browser = await self.playwright.chromium.launch(
                                **launch_options
                            )
                        else:
                            raise
                    context_options.pop("args", None)
                    context_options.pop("channel", None)
                    context_options.pop("headless", None)
                    # proxy остаётся в context_options — применяется ко всему context (все страницы и popup)
                    if getattr(settings, "BROWSER_RECORD_VIDEO", True):
                        context_options["record_video_dir"] = str(video_dir)
                        context_options["record_video_size"] = {
                            "width": 1280,
                            "height": 720,
                        }
                        logger.info("Запись видео сессии включена (videos/)")
                    self.context = await self.browser.new_context(**context_options)

                # Увеличенные таймауты для работы через прокси (медленная загрузка)
                self.context.set_default_navigation_timeout(
                    120000
                )  # 120 сек (2 мин) на навигацию
                self.context.set_default_timeout(
                    60000
                )  # 60 сек на действия (селекторы и т.д.)

                self.page = await self.context.new_page()

                if not use_patchright:
                    await self._apply_cdp_webdriver_patch()
                    use_stealth_plugin = getattr(
                        settings, "BROWSER_USE_STEALTH_PLUGIN", True
                    )
                    if use_stealth_plugin:
                        try:
                            from playwright_stealth import stealth_async

                            await stealth_async(self.page)
                        except ImportError:
                            logger.debug(
                                "playwright-stealth не установлен (опционально)"
                            )
                    await self._inject_context_stealth_scripts()
                    await self._inject_page_stealth_scripts()
                else:
                    logger.debug(
                        "Patchright: только встроенные патчи (рекомендуемый режим)"
                    )

                # Прогрев: первый запрос — about:blank, чтобы первый переход на Supercell не был «холодным»
                if getattr(settings, "BROWSER_WARMUP", True):
                    try:
                        await self.page.goto(
                            "about:blank", wait_until="commit", timeout=5000
                        )
                        await self.page.wait_for_timeout(random.randint(2000, 3500))
                        logger.info("Браузер прогрет (about:blank)")
                    except Exception as e:
                        logger.debug(f"Прогрев браузера пропущен: {e}")

                # Browsec VPN: включить и выбрать регион US (расширение должно быть установлено в Chrome)
                if getattr(settings, "BROWSER_USE_BROWSEC_VPN", False):
                    await self._enable_browsec_vpn_region()

                logger.info("Браузер успешно запущен с улучшенным stealth режимом")
                return  # Успешно запущен

            except Exception as e:
                last_error = e
                error_msg = str(e).lower()

                # Закрываем браузер при ошибке
                try:
                    if hasattr(self, "browser") and self.browser:
                        await self.browser.close()
                    if hasattr(self, "playwright") and self.playwright:
                        await self.playwright.stop()
                except:
                    pass

                # Проверяем, связана ли ошибка с прокси
                is_proxy_error = any(
                    [
                        "err_empty_response" in error_msg,
                        "net::err_" in error_msg,
                        "proxy" in error_msg,
                        "connection" in error_msg and "refused" in error_msg,
                        "timeout" in error_msg and proxy is not None,
                    ]
                )

                if (
                    is_proxy_error
                    and proxy
                    and retry_proxy
                    and proxy_attempts < max_proxy_retries - 1
                ):
                    proxy_attempts += 1
                    logger.warning(
                        f"Ошибка подключения через прокси {proxy.get('server', 'unknown')}: {e}. "
                        f"Попытка {proxy_attempts + 1}/{max_proxy_retries}: пробуем другой прокси..."
                    )

                    # Помечаем прокси как провалившийся
                    proxy_manager.mark_proxy_failed(proxy)

                    # Небольшая задержка перед следующей попыткой
                    await asyncio.sleep(2)
                    continue
                else:
                    # Если это не ошибка прокси, или попытки закончились, пробрасываем ошибку
                    if proxy_attempts >= max_proxy_retries - 1:
                        logger.error(
                            f"Не удалось запустить браузер после {max_proxy_retries} попыток. "
                            f"Последняя ошибка: {last_error}"
                        )
                        if proxy:
                            raise Exception(
                                f"Ошибка подключения через прокси после {max_proxy_retries} попыток: {last_error}. "
                                f"Проверьте настройки прокси в proxies.txt или отключите прокси в .env (PROXY_ENABLED=false)"
                            )
                    raise

    async def _enable_browsec_vpn_region(self) -> None:
        """
        Открыть расширение Browsec VPN и включить его с выбранным регионом (по умолчанию US).
        Требуется: Chrome с установленным Browsec из Chrome Web Store; BROWSER_USE_SYSTEM_PROFILE=true.
        """
        if not self.context:
            return
        region = (
            (getattr(settings, "BROWSER_BROWSEC_VPN_REGION", "US") or "US")
            .strip()
            .upper()
        )
        # ID расширения Browsec VPN в Chrome Web Store
        BROWSEC_EXTENSION_ID = "omghfjlpggmjjaagoclmmobgdodcjboh"
        ext_url = f"chrome-extension://{BROWSEC_EXTENSION_ID}/popup.html"
        ext_page = None
        try:
            ext_page = await self.context.new_page()
            await ext_page.goto(ext_url, wait_until="domcontentloaded", timeout=10000)
            await ext_page.wait_for_timeout(1500)
            # Включить VPN: кнопка "Protect me" / "Turn on" / переключатель
            for selector in [
                'button:has-text("Protect")',
                'button:has-text("Turn on")',
                'button:has-text("Enable")',
                '[role="switch"]',
                'button:has-text("ON")',
                'a:has-text("Protect")',
            ]:
                try:
                    btn = await ext_page.wait_for_selector(selector, timeout=2000)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await ext_page.wait_for_timeout(1000)
                        break
                except Exception:
                    continue
            # Выбрать регион US
            for selector in [
                f'button:has-text("{region}")',
                f'a:has-text("{region}")',
                f'[data-country="{region}"]',
                "text=United States",
                "text=USA",
            ]:
                try:
                    el = await ext_page.wait_for_selector(selector, timeout=2000)
                    if el and await el.is_visible():
                        await el.click()
                        await ext_page.wait_for_timeout(800)
                        logger.info("Browsec VPN: включён регион %s", region)
                        break
                except Exception:
                    continue
            await ext_page.close()
        except Exception as e:
            logger.warning(
                "Browsec VPN: не удалось включить (установите расширение из Chrome Web Store и закройте Chrome перед запуском): %s",
                e,
            )
            try:
                if ext_page:
                    await ext_page.close()
            except Exception:
                pass

    async def _apply_cdp_webdriver_patch(self) -> None:
        """
        Через CDP убираем navigator.webdriver.
        Используем два метода:
        1. addScriptToEvaluateOnNewDocument — для будущих загрузок страниц
        2. Runtime.evaluate — немедленное выполнение на текущей странице
        """
        if not self.page or not self.context:
            return

        webdriver_patch = """
(function() {
    // Шаг 1: удаляем с прототипа Navigator
    try { delete Object.getPrototypeOf(navigator).webdriver; } catch(e) {}

    // Шаг 2: удаляем напрямую с объекта navigator (Playwright добавляет сюда)
    try { delete navigator.webdriver; } catch(e) {}

    // Шаг 3: переопределяем через defineProperty — скрываем значение И присутствие
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            set: () => {},
            configurable: true,
            enumerable: false
        });
    } catch(e) {}

    // Шаг 4: Proxy на navigator чтобы 'webdriver' in navigator возвращал false
    // Это единственный способ скрыть свойство от оператора 'in'
    try {
        const navProxy = new Proxy(navigator, {
            has: function(target, key) {
                if (key === 'webdriver') return false;
                return key in target;
            },
            get: function(target, key) {
                if (key === 'webdriver') return undefined;
                const val = target[key];
                if (typeof val === 'function') return val.bind(target);
                return val;
            }
        });
        // Заменяем window.navigator на Proxy
        Object.defineProperty(window, 'navigator', {
            get: () => navProxy,
            configurable: true,
            enumerable: true
        });
    } catch(e) {}

    // Шаг 5: Cdc / Selenium артефакты
    var cdcKeys = ['$cdc_asdjflasutopfhvcZLmcfl_', '$chrome_asyncScriptInfo',
        '__webdriver_evaluate', '__selenium_evaluate', '__webdriver_script_function',
        '__webdriver_script_func', '__webdriver_script_fn', '__fxdriver_evaluate',
        '__driver_unwrapped', '__webdriver_unwrapped', '__driver_evaluate',
        '__selenium_unwrapped', '__fxdriver_unwrapped'];
    cdcKeys.forEach(function(k) {
        try { delete window[k]; } catch(e) {}
        try { Object.defineProperty(window, k, {get: function(){return undefined;}, configurable: true, enumerable: false}); } catch(e) {}
    });
})();
"""
        # Патч Permissions API — reCAPTCHA и сайты проверяют navigator.permissions.query
        # В автоматизации ответ может отличаться; возвращаем «нормальный» prompt/granted
        permissions_patch = """
(function() {
    if (!navigator.permissions || !navigator.permissions.query) return;
    var realQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = function(desc) {
        return realQuery(desc).then(function(result) {
            return result;
        }).catch(function() {
            return { state: 'prompt', onchange: null };
        });
    };
})();
"""
        try:
            cdp = await self.context.new_cdp_session(self.page)
            await cdp.send(
                "Page.addScriptToEvaluateOnNewDocument", {"source": webdriver_patch}
            )
            await cdp.send(
                "Runtime.evaluate",
                {"expression": webdriver_patch, "returnByValue": False},
            )
            await cdp.send(
                "Page.addScriptToEvaluateOnNewDocument", {"source": permissions_patch}
            )
            logger.debug("CDP: патч navigator.webdriver и Permissions API применён")
        except Exception as e:
            logger.debug(f"CDP патч не применён (не критично): {e}")

    async def _inject_context_stealth_scripts(self) -> None:
        """Инъекция stealth скриптов через контекст (применяется ко всем страницам)."""
        if not self.context:
            return

        comprehensive_stealth = """
(function() {
    'use strict';

    // 1. webdriver — удаляем значение (Proxy для 'in' оператора — только в CDP патче)
    try { delete Object.getPrototypeOf(navigator).webdriver; } catch(e) {}
    try { delete navigator.webdriver; } catch(e) {}
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined, set: () => {},
            configurable: true, enumerable: false
        });
    } catch(e) {}

    // 2. Cdc / Selenium артефакты (ChromeDriver оставляет эти переменные)
    const cdcKeys = [
        '$cdc_asdjflasutopfhvcZLmcfl_', '$chrome_asyncScriptInfo',
        '__webdriver_evaluate', '__selenium_evaluate',
        '__webdriver_script_function', '__webdriver_script_func',
        '__webdriver_script_fn', '__fxdriver_evaluate',
        '__driver_unwrapped', '__webdriver_unwrapped',
        '__driver_evaluate', '__selenium_unwrapped',
        '__fxdriver_unwrapped', '_Selenium_IDE_Recorder',
        '_selenium', 'calledSelenium',
    ];
    cdcKeys.forEach(function(k) {
        try { delete window[k]; } catch(e) {}
        try { Object.defineProperty(window, k, { get: () => undefined, configurable: true, enumerable: false }); } catch(e) {}
    });

    // 3. Plugins — реалистичный список с правильным прототипом
    try {
        Object.defineProperty(navigator, 'plugins', {
            get: function() {
                const arr = Object.create(PluginArray.prototype);
                const pluginDefs = [
                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format',
                      mimes: [{ type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' }] },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '',
                      mimes: [{ type: 'application/pdf', suffixes: 'pdf', description: '' }] },
                    { name: 'Native Client', filename: 'internal-nacl-plugin', description: '',
                      mimes: [
                        { type: 'application/x-nacl', suffixes: '', description: 'Native Client Executable' },
                        { type: 'application/x-pnacl', suffixes: '', description: 'Portable Native Client Executable' }
                      ] },
                ];
                pluginDefs.forEach(function(def, i) {
                    const plugin = Object.create(Plugin.prototype);
                    plugin.name = def.name;
                    plugin.filename = def.filename;
                    plugin.description = def.description;
                    plugin.length = def.mimes.length;
                    def.mimes.forEach(function(m, j) {
                        const mime = Object.create(MimeType.prototype);
                        mime.type = m.type;
                        mime.suffixes = m.suffixes;
                        mime.description = m.description;
                        mime.enabledPlugin = plugin;
                        plugin[j] = mime;
                    });
                    arr[i] = plugin;
                });
                arr.length = pluginDefs.length;
                arr.item = function(i) { return arr[i] || null; };
                arr.namedItem = function(n) {
                    for (let i = 0; i < arr.length; i++) {
                        if (arr[i] && arr[i].name === n) return arr[i];
                    }
                    return null;
                };
                arr.refresh = function() {};
                return arr;
            },
            configurable: true,
            enumerable: true
        });
    } catch(e) {}

    // 4. Languages
    try {
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
            configurable: true
        });
    } catch(e) {}

    // 5. window.chrome — полная имитация реального Chrome
    try {
        window.chrome = {
            app: {
                isInstalled: false,
                InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
                getDetails: function() { return null; },
                getIsInstalled: function() { return false; },
                installState: function(cb) { cb('not_installed'); },
                runningState: function() { return 'cannot_run'; }
            },
            runtime: {
                OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
                PlatformArch: { ARM: 'arm', ARM64: 'arm64', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', WIN: 'win' },
                connect: function() { return { disconnect: function() {}, onDisconnect: { addListener: function() {} }, onMessage: { addListener: function() {} }, postMessage: function() {} }; },
                sendMessage: function() {},
                id: undefined
            },
            loadTimes: function() {
                return {
                    commitLoadTime: Date.now() / 1000 - 1,
                    connectionInfo: 'http/1.1',
                    finishDocumentLoadTime: Date.now() / 1000,
                    finishLoadTime: Date.now() / 1000,
                    firstPaintAfterLoadTime: 0,
                    firstPaintTime: Date.now() / 1000 - 0.5,
                    navigationType: 'Other',
                    npnNegotiatedProtocol: 'unknown',
                    requestTime: Date.now() / 1000 - 2,
                    startLoadTime: Date.now() / 1000 - 1.5,
                    wasAlternateProtocolAvailable: false,
                    wasFetchedViaSpdy: false,
                    wasNpnNegotiated: false
                };
            },
            csi: function() {
                return { onloadT: Date.now(), pageT: 3000 + Math.random() * 2000, startE: Date.now() - 1000, tran: 15 };
            }
        };
    } catch(e) {}

    // 6. Permissions API
    try {
        const origQuery = window.navigator.permissions.query.bind(navigator.permissions);
        window.navigator.permissions.__proto__.query = function(parameters) {
            if (parameters.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission, onchange: null });
            }
            return origQuery(parameters);
        };
    } catch(e) {}

    // 7. WebGL — реалистичные значения
    try {
        const getParam = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParam.call(this, parameter);
        };
    } catch(e) {}
    try {
        const getParam2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParam2.call(this, parameter);
        };
    } catch(e) {}

    // 8. Hardware concurrency & deviceMemory
    try { Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8, configurable: true }); } catch(e) {}
    try { Object.defineProperty(navigator, 'deviceMemory', { get: () => 8, configurable: true }); } catch(e) {}

    // 9. Platform
    try { Object.defineProperty(navigator, 'platform', { get: () => 'Win32', configurable: true }); } catch(e) {}

    // 10. Connection
    try {
        Object.defineProperty(navigator, 'connection', {
            get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }),
            configurable: true
        });
    } catch(e) {}

    // 11. document.documentElement.webdriver
    try {
        Object.defineProperty(document.documentElement, 'webdriver', {
            get: () => undefined,
            configurable: true,
            enumerable: false
        });
    } catch(e) {}

    // 12. Battery API
    try {
        if (navigator.getBattery) {
            navigator.getBattery = () => Promise.resolve({
                charging: true, chargingTime: 0,
                dischargingTime: Infinity, level: 0.95
            });
        }
    } catch(e) {}

})();
        """

        try:
            await self.context.add_init_script(comprehensive_stealth)
            logger.debug("Stealth скрипты применены через контекст")
        except Exception as e:
            logger.debug(f"Ошибка инъекции stealth скрипта в контекст: {e}")

    async def _inject_page_stealth_scripts(self) -> None:
        """Дополнительные stealth скрипты для конкретной страницы (минимальные — основное в контексте)."""
        pass

    async def human_like_delay(self, min_ms: int = 100, max_ms: int = 500) -> None:
        """Случайная задержка для имитации человеческого поведения."""
        delay = random.randint(min_ms, max_ms)
        await self.page.wait_for_timeout(delay)

    async def human_like_type(
        self, selector: str, text: str, delay_between_chars: int = 80
    ) -> None:
        """
        Ввод текста максимально похожий на человека.
        НЕ использует fill() — только реальные нажатия клавиш через keyboard.
        """
        if not self.page:
            raise RuntimeError("Страница не инициализирована")

        element = await self.page.query_selector(selector)
        if not element:
            return

        # Получаем bounding box и двигаем мышь к полю
        box = await element.bounding_box()
        if box:
            # Двигаем мышь к полю с небольшим смещением (не точно в центр)
            target_x = box["x"] + box["width"] * (0.3 + random.random() * 0.4)
            target_y = box["y"] + box["height"] * (0.3 + random.random() * 0.4)
            await self.page.mouse.move(target_x, target_y)
            await self.page.wait_for_timeout(random.randint(150, 350))

        # Реальный клик (mousedown + mouseup) — не JS click()
        await element.click(delay=random.randint(50, 120))
        await self.page.wait_for_timeout(random.randint(200, 500))

        # Выделяем всё и удаляем (Ctrl+A, Delete) — без fill()
        await self.page.keyboard.press("Control+a")
        await self.page.wait_for_timeout(random.randint(50, 150))
        await self.page.keyboard.press("Delete")
        await self.page.wait_for_timeout(random.randint(100, 250))

        # Вводим текст посимвольно с нерегулярными задержками (имитация реального набора)
        for i, char in enumerate(text):
            # Нерегулярные задержки: иногда быстрее, иногда медленнее
            base_delay = delay_between_chars
            jitter = random.randint(-30, 60)
            char_delay = max(40, base_delay + jitter)
            # Иногда делаем паузу (как будто думаем)
            if random.random() < 0.08:
                await self.page.wait_for_timeout(random.randint(200, 600))
            await self.page.keyboard.type(char)
            await self.page.wait_for_timeout(char_delay)

    async def navigate_to_store(self, game: str = "clash-royale") -> None:
        """Переход в магазин игры: клик по карточке на главной store.supercell.com (не по прямой ссылке)."""
        if not self.page:
            await self.start()

        # Тексты карточек на главной store.supercell.com (например "Brawl Stars Store", "Clash Royale Store")
        card_texts = {
            "brawl-stars": ["Brawl Stars Store", "Brawl Stars", "brawl stars store"],
            "clash-royale": [
                "Clash Royale Store",
                "Clash Royale",
                "clash royale store",
            ],
        }
        texts = card_texts.get(game.lower(), [f"{game} Store", game])

        logger.info(f"Переход в магазин {game}: ищем карточку на главной и нажимаем")

        clicked = False
        for text in texts:
            try:
                # Ссылка или кнопка с текстом карточки (partial match)
                loc = self.page.get_by_role("link", name=text)
                if await loc.count() > 0:
                    await loc.first.click()
                    clicked = True
                    logger.info(f"Клик по карточке (link): {text}")
                    break
            except Exception:
                pass
            if clicked:
                break
            try:
                await self.page.click(f"text={text}", timeout=5000)
                clicked = True
                logger.info(f"Клик по карточке (text): {text}")
                break
            except Exception:
                pass
            try:
                # Ссылка по href (например /brawl-stars, /clash-royale)
                slug = game.lower().replace("_", "-")
                link = await self.page.query_selector(f'a[href*="{slug}"]')
                if link and await link.is_visible():
                    await link.click()
                    clicked = True
                    logger.info(f"Клик по ссылке магазина: href*={slug}")
                    break
            except Exception:
                pass

        if not clicked:
            # Fallback: прямой переход по URL
            url_map = {
                "clash-royale": settings.CLASH_ROYALE_STORE_URL,
                "brawl-stars": settings.BRAWL_STARS_STORE_URL,
            }
            url = url_map.get(game.lower(), settings.SUPERCELL_STORE_URL)
            logger.warning(f"Карточка магазина не найдена, переход по URL: {url}")
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logger.error(f"Ошибка перехода на страницу: {e}")
                raise
        else:
            # Дождаться перехода на страницу магазина (чтобы не «висеть на одном месте»)
            slug = game.lower().replace("_", "-").replace(" ", "-")
            try:
                # URL может быть /brawlstars или /brawl-stars, /clashroyale или /clash-royale
                slug_re = slug.replace("-", "[-]?")
                url_pattern = re.compile(rf".*{slug_re}.*", re.I)
                await self.page.wait_for_url(url_pattern, timeout=25000)
                logger.info(f"Переход на магазин завершён: {self.page.url}")
            except Exception:
                pass
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=30000)
                await self.human_like_delay(2000, 4000)
            except Exception:
                pass

    async def take_screenshot(self, filename: str, timeout_ms: int = 20000) -> Path:
        """
        Сделать скриншот страницы.
        timeout_ms: ограничение ожидания (по умолчанию 20 сек), чтобы не висеть на «waiting for fonts to load».
        """
        if not self.page:
            raise RuntimeError("Страница не инициализирована")

        # Используем абсолютный путь через resolve() — критично для headed режима
        # с persistent profile: Chromium стартует из директории профиля (/app/browser_profile),
        # и относительный путь "screenshots/..." Playwright разрешает относительно CWD
        # браузера, а не Python-процесса → FileNotFoundError.
        # resolve() преобразует "screenshots" → "/app/screenshots" (абсолютный путь),
        # который корректно работает и в headless, и в headed+persistent режимах.
        try:
            project_root = Path(__file__).resolve().parent.parent.parent
        except Exception:
            project_root = Path.cwd()
        screenshot_dir = (project_root / "screenshots").resolve()
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        filepath = screenshot_dir / filename
        filepath_abs = str(filepath)

        try:
            await self.page.screenshot(
                path=filepath_abs,
                full_page=True,
                timeout=timeout_ms,
            )
        except Exception as e:
            # При таймауте (например из-за шрифтов) пробуем скриншот без full_page и с коротким таймаутом
            if "timeout" in str(e).lower() or "exceeded" in str(e).lower():
                logger.warning(
                    f"Скриншот full_page таймаут ({timeout_ms} мс), пробуем viewport..."
                )
                try:
                    await self.page.screenshot(path=filepath_abs, timeout=5000)
                except Exception:
                    raise e
            else:
                raise
        # Возвращаем относительный путь (для отображения в API-ответах и логах)
        rel_path = Path("screenshots") / filename
        logger.info(f"Скриншот сохранен: {rel_path}")
        return rel_path

    async def get_page_content(self) -> Dict[str, any]:
        """Получить содержимое страницы для AI-анализа."""
        if not self.page:
            raise RuntimeError("Страница не инициализирована")

        # Получаем HTML структуру
        html = await self.page.content()

        # Получаем видимые текстовые элементы
        visible_text = await self.page.evaluate(
            """
            () => {
                const elements = document.querySelectorAll('*');
                const texts = [];
                elements.forEach(el => {
                    if (el.offsetParent !== null && el.textContent.trim()) {
                        const rect = el.getBoundingClientRect();
                        texts.push({
                            text: el.textContent.trim(),
                            tag: el.tagName,
                            x: rect.x,
                            y: rect.y,
                            width: rect.width,
                            height: rect.height
                        });
                    }
                });
                return texts;
            }
            """
        )

        # Делаем скриншот для визуального анализа
        screenshot_path = await self.take_screenshot("page_analysis.png")

        return {
            "html": html,
            "visible_elements": visible_text,
            "screenshot": str(screenshot_path),
            "url": self.page.url,
        }

    async def click_element_by_text(
        self, text: str, partial: bool = True, timeout: int = 10000
    ) -> bool:
        """Клик по элементу по тексту."""
        if not self.page:
            raise RuntimeError("Страница не инициализирована")

        try:
            if partial:
                selector = f"text={text}"
            else:
                selector = f"text='{text}'"

            await self.page.click(selector, timeout=timeout)
            logger.info(f"Клик по элементу с текстом: {text}")
            return True
        except Exception as e:
            logger.error(f"Ошибка клика по элементу '{text}': {e}")
            return False

    async def fill_input(self, selector: str, value: str, timeout: int = 10000) -> bool:
        """Заполнить поле ввода."""
        if not self.page:
            raise RuntimeError("Страница не инициализирована")

        try:
            await self.page.fill(selector, value, timeout=timeout)
            logger.info(f"Заполнено поле {selector}")
            return True
        except Exception as e:
            logger.error(f"Ошибка заполнения поля {selector}: {e}")
            return False

    async def wait_for_element(
        self, selector: str, timeout: int = 30000
    ) -> Optional[any]:
        """Ожидание появления элемента."""
        if not self.page:
            raise RuntimeError("Страница не инициализирована")

        try:
            element = await self.page.wait_for_selector(selector, timeout=timeout)
            return element
        except Exception as e:
            logger.error(f"Элемент {selector} не найден: {e}")
            return None

    async def navigate_to_supercell_login(self) -> None:
        """Переход на страницу логина Supercell (store) с обработкой загрузки и cookies."""
        if not self.page:
            raise RuntimeError("Страница не инициализирована")

        url = "https://store.supercell.com"
        logger.info(f"Переход на {url}")

        try:
            response = await self.page.goto(
                url,
                wait_until="networkidle",
                timeout=60000,
            )

            if not response or response.status >= 400:
                raise RuntimeError(
                    f"Ошибка загрузки страницы: {response.status if response else 'no response'}"
                )

            await self.page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)

            await self._handle_cookies()

            logger.info(f"Страница загружена: {self.page.url}")

        except Exception as e:
            logger.error(f"Ошибка навигации: {e}")
            await self.take_screenshot("navigation_error.png")
            raise

    async def _handle_cookies(self) -> None:
        """Обработка cookie баннера на странице (Supercell: «Accept All Cookies»)."""
        if not self.page:
            return
        await self.page.wait_for_timeout(1500)
        for label in ["Accept All Cookies", "Accept All", "Accept Cookies"]:
            try:
                btn = self.page.get_by_role("button", name=label)
                await btn.first.wait_for(state="visible", timeout=3000)
                await btn.first.click(force=True)
                logger.info(f"Cookies приняты: {label}")
                await asyncio.sleep(1)
                return
            except Exception:
                continue
        for selector in [
            'button:has-text("Accept All Cookies")',
            'button:has-text("Accept All")',
            'button:has-text("Accept")',
        ]:
            try:
                button = await self.page.wait_for_selector(
                    selector, timeout=2000, state="visible"
                )
                if button:
                    await button.click(force=True)
                    logger.info(f"Cookies приняты ({selector})")
                    await asyncio.sleep(1)
                    return
            except Exception:
                continue
        logger.debug("Cookie баннер не найден или уже принят")

    async def login_supercell(
        self, email: str, verification_code: Optional[str] = None
    ) -> Dict:
        """
        Авторизация в Supercell Store (email → код из письма).
        Используется как альтернативный поток; API использует свой сценарий в supercell_auth_routes.

        Args:
            email: Email для входа
            verification_code: 6-значный код из письма (если есть)

        Returns:
            Dict со status, url, message и при необходимости screenshot.
        """
        if not self.page:
            raise RuntimeError("Страница не инициализирована")

        logger.info(f"Начинаем авторизацию: {email}")

        try:
            logger.info("Ожидание формы логина...")
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[placeholder*="email" i]',
                'input[placeholder*="Email" i]',
                '[data-testid="email-input"]',
                'input[id*="email" i]',
            ]

            email_input = None
            for selector in email_selectors:
                try:
                    email_input = await self.page.wait_for_selector(
                        selector,
                        timeout=5000,
                        state="visible",
                    )
                    if email_input:
                        logger.info(f"Найдено поле email: {selector}")
                        break
                except Exception:
                    continue

            if not email_input:
                await self.take_screenshot("email_field_not_found.png")
                raise RuntimeError("Поле email не найдено")

            await email_input.click()
            await asyncio.sleep(0.5)
            await email_input.fill("")
            await asyncio.sleep(0.3)

            for char in email:
                await email_input.type(char, delay=random.randint(50, 150))

            logger.info(f"Email введён: {email}")
            await self.take_screenshot("email_entered.png")

            login_button_selectors = [
                'button:has-text("LOG IN")',
                'button:has-text("Log in")',
                'button[type="submit"]',
                '[data-testid="login-button"]',
                'button:has-text("Continue")',
                'button:has-text("Next")',
            ]

            login_button = None
            for selector in login_button_selectors:
                try:
                    login_button = await self.page.wait_for_selector(
                        selector,
                        timeout=3000,
                        state="visible",
                    )
                    if login_button:
                        logger.info(f"Найдена кнопка логина: {selector}")
                        break
                except Exception:
                    continue

            if not login_button:
                raise RuntimeError("Кнопка логина не найдена")

            is_disabled = await login_button.is_disabled()
            if is_disabled:
                logger.info("Кнопка логина disabled, ждём...")
                await self.page.wait_for_function(
                    """() => {
                        const btns = document.querySelectorAll('button[type="submit"], button');
                        for (const b of btns) {
                            if (b.textContent && b.textContent.includes('LOG IN') && !b.disabled) return true;
                        }
                        return false;
                    }""",
                    timeout=10000,
                )

            await login_button.click()
            logger.info("Кнопка LOG IN нажата")

            logger.info("Ожидание окна ввода кода...")
            try:
                code_selectors = [
                    'input[type="text"][maxlength="6"]',
                    'input[placeholder*="code" i]',
                    'input[name="code"]',
                    '[data-testid="verification-code"]',
                    'input[inputmode="numeric"]',
                ]

                code_input = None
                for selector in code_selectors:
                    try:
                        code_input = await self.page.wait_for_selector(
                            selector,
                            timeout=15000,
                            state="visible",
                        )
                        if code_input:
                            logger.info(f"Найдено поле кода: {selector}")
                            break
                    except Exception:
                        continue

                if code_input:
                    await self.take_screenshot("code_input_appeared.png")

                    if verification_code:
                        for char in verification_code:
                            await code_input.type(char, delay=random.randint(100, 200))
                        logger.info("Код введён")
                        await asyncio.sleep(1)
                        await self.take_screenshot("code_entered.png")
                    else:
                        logger.info("Код не предоставлен, ожидание ввода...")
                        return {
                            "status": "code_required",
                            "message": "Требуется код верификации из email",
                            "screenshot": str(
                                await self.take_screenshot("awaiting_code.png")
                            ),
                        }
                else:
                    error_text = await self.page.evaluate(
                        """() => {
                            const errorEl = document.querySelector('.error, .alert, [role="alert"]');
                            return errorEl ? errorEl.textContent : null;
                        }"""
                    )
                    if error_text:
                        raise RuntimeError(f"Ошибка на странице: {error_text}")
                    current_url = self.page.url
                    if "verify" in current_url or "code" in current_url:
                        logger.info("Перешли на страницу верификации")
                    else:
                        logger.warning(f"Неожиданный URL: {current_url}")
                        await self.take_screenshot("unexpected_page.png")

            except Exception as e:
                logger.error(f"Ошибка при ожидании кода: {e}")
                await self.take_screenshot("code_wait_error.png")
                raise

            return {
                "status": "success",
                "url": self.page.url,
                "message": "Авторизация успешна",
            }

        except Exception as e:
            logger.error(f"Ошибка авторизации: {e}")
            await self.take_screenshot("login_error.png")
            raise

    async def close(self):
        """
        Закрытие браузера. Сохраняет запись видео при закрытии контекста.
        Returns:
            Path к сохранённому видео (str) или None.
        """
        video_path = None
        try:
            if self.page and self.context:
                try:
                    video = self.page.video
                    if video:
                        await self.context.close()
                        self.context = None
                        path = await video.path()
                        video_path = str(path) if path else None
                        if video_path:
                            logger.info(f"Видео сессии сохранено: {video_path}")
                except Exception as ve:
                    logger.debug(f"Не удалось сохранить видео: {ve}")
            if self.context:
                await self.context.close()
                self.context = None
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            logger.info("Браузер закрыт")
        except Exception as e:
            logger.error(f"Ошибка закрытия браузера: {e}")
        return video_path

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

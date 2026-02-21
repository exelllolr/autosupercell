"""Менеджер прокси для ротации и управления."""

import random
import asyncio
import secrets
from typing import Optional, List, Dict, Any
from pathlib import Path
from loguru import logger
from app.config import settings


class ProxyManager:
    """Управление прокси-серверами с ротацией."""

    def __init__(self):
        """Инициализация менеджера прокси."""
        self.proxies: List[Dict[str, Any]] = []
        self.current_proxy_index: int = 0
        self.failed_proxies: set = set()
        self._load_proxies()

    def _load_proxies(self) -> None:
        """Загрузка списка прокси из файла и/или Novada из конфига."""
        if not settings.PROXY_ENABLED:
            logger.info("Прокси отключены в конфигурации")
            return

        # Novada: добавляем как «шаблон» — при каждом get_proxy() подставляем новый session = новый IP
        novada_enabled = getattr(settings, "NOVADA_ENABLED", False)
        novada_user = getattr(settings, "NOVADA_USERNAME", "") or ""
        novada_key = getattr(settings, "NOVADA_API_KEY", "") or ""
        if novada_enabled and novada_user and novada_key:
            zone = getattr(settings, "NOVADA_ZONE", "res") or "res"
            region = getattr(settings, "NOVADA_REGION", "") or ""
            host = getattr(settings, "NOVADA_PROXY_HOST", "super.novada.pro") or "super.novada.pro"
            port = getattr(settings, "NOVADA_PROXY_PORT", 7777) or 7777
            sticky_min = getattr(settings, "NOVADA_STICKY_MINUTES", 0) or 0
            if sticky_min < 0:
                sticky_min = 0
            if sticky_min > 120:
                sticky_min = 120
            username_base = f"{novada_user}-zone-{zone}"
            if region:
                username_base += f"-region-{region.lower()}"
            self.proxies.append({
                "server": f"http://{host}:{port}",
                "password": novada_key,
                "_novada_fresh_session": True,
                "_novada_username_base": username_base,
                "_novada_sticky_min": sticky_min,
            })
            logger.info(
                f"Добавлен Novada прокси (zone={zone}, region={region or 'any'}). "
                f"Новый IP на каждый запуск браузера. Сервер: {host}:{port}"
            )

        proxy_file = Path(settings.PROXY_LIST_FILE)
        if not proxy_file.exists():
            if self.proxies:
                logger.info(f"Загружено прокси: {len(self.proxies)} (Novada)")
            else:
                logger.warning(f"Файл прокси {proxy_file} не найден и Novada не задан")
            return

        try:
            with open(proxy_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Поддержка Bright Data формата: Api=API_KEY
                    if line.startswith("Api="):
                        api_key = line.split("=", 1)[1].strip()
                        # Bright Data резидентный прокси
                        proxy_dict = {
                            "server": "http://brd.superproxy.io:33335",
                            "username": f"{api_key}-country-us",
                            "password": "",  # Bright Data может не требовать пароль
                        }
                        self.proxies.append(proxy_dict)
                        logger.info(f"Добавлен Bright Data прокси (US)")
                        continue

                    # Поддержка различных форматов прокси
                    # Формат 1: user:pass@host:port (Webshare стандартный)
                    if "@" in line:
                        auth, proxy = line.split("@")
                        user, password = auth.split(":")
                        host, port = proxy.split(":")
                        proxy_dict = {
                            "server": f"http://{host}:{port}",
                            "username": user,
                            "password": password,
                        }
                    # Формат 2: host:port:user:pass (Webshare альтернативный)
                    elif line.count(":") == 3:
                        parts = line.split(":")
                        host, port, user, password = parts
                        proxy_dict = {
                            "server": f"http://{host}:{port}",
                            "username": user,
                            "password": password,
                        }
                    # Формат 3: host:port (без авторизации)
                    else:
                        host, port = line.split(":")
                        proxy_dict = {"server": f"http://{host}:{port}"}

                    self.proxies.append(proxy_dict)

            logger.info(f"Загружено {len(self.proxies)} прокси")
        except Exception as e:
            logger.error(f"Ошибка загрузки прокси: {e}")

    def get_proxy(self) -> Optional[Dict[str, str]]:
        """
        Получить следующий прокси с ротацией.
        
        Если PROXY_USE_FIRST_ONLY=True — всегда возвращает первый прокси.
        Иначе — последовательно выбирает следующий доступный прокси (пропуская failed).
        """
        if not settings.PROXY_ENABLED or not self.proxies:
            return None

        if getattr(settings, "PROXY_USE_FIRST_ONLY", False):
            proxy = self._resolve_proxy(self.proxies[0])
            logger.info(f"Используется первый прокси (PROXY_USE_FIRST_ONLY): {proxy.get('server')}")
            return proxy

        # Получаем список доступных прокси (исключая failed)
        available_indices = [
            i for i in range(len(self.proxies)) if i not in self.failed_proxies
        ]
        
        if not available_indices:
            # Если все прокси провалились, сбрасываем список и используем все
            logger.warning("Все прокси провалились, сбрасываем список failed прокси")
            self.failed_proxies.clear()
            available_indices = list(range(len(self.proxies)))
        
        if settings.PROXY_ROTATION_ENABLED:
            # Случайный выбор из доступных
            chosen_index = random.choice(available_indices)
        else:
            # Последовательный выбор: берём текущий индекс, если он доступен; иначе — следующий доступный с циклом.
            n = len(self.proxies)
            start = self.current_proxy_index % n
            chosen_index = None
            for offset in range(n):
                idx = (start + offset) % n
                if idx in available_indices:
                    chosen_index = idx
                    break
            if chosen_index is None:
                chosen_index = available_indices[0]

        # Обновляем индекс старта на "следующий после выбранного" для последовательного режима,
        # чтобы следующий вызов возвращал следующий прокси.
        if not settings.PROXY_ROTATION_ENABLED:
            self.current_proxy_index = (chosen_index + 1) % len(self.proxies)
        else:
            self.current_proxy_index = chosen_index
        proxy = self._resolve_proxy(self.proxies[chosen_index])
        
        # Логируем выбранный прокси
        server = proxy.get("server", "unknown")
        username = proxy.get("username", "")
        logger.info(
            f"Выбран прокси [{chosen_index + 1}/{len(self.proxies)}]: "
            f"{server} (user: {username})"
        )
        
        return proxy

    def _resolve_proxy(self, entry: Dict[str, Any]) -> Dict[str, str]:
        """
        Превращает запись из self.proxies в итоговый dict для Playwright.
        Для Novada с _novada_fresh_session подставляет новый session ID = новый IP на каждый вызов.
        """
        if not entry.get("_novada_fresh_session"):
            return {k: v for k, v in entry.items() if not str(k).startswith("_")}
        base = entry.get("_novada_username_base", "")
        sticky = entry.get("_novada_sticky_min", 0)
        session_id = secrets.token_hex(6)
        username = f"{base}-session-{session_id}-sessTime-{sticky}"
        logger.info(
            f"Novada: новый IP для этого запуска (session-id: {session_id}), "
            f"шлюз один — выходной адрес у Novada меняется по session"
        )
        return {
            "server": entry["server"],
            "username": username,
            "password": entry["password"],
        }

    def mark_proxy_failed(self, proxy: Dict[str, str]) -> None:
        """
        Пометить прокси как провалившийся.
        Для обычных прокси — по server+username+password.
        Для Novada (шаблон без username в списке) — по server.
        """
        if not proxy:
            return
        
        target_server = proxy.get("server", "")
        target_username = proxy.get("username", "") or ""
        target_password = proxy.get("password", "") or ""
        
        for index, p in enumerate(self.proxies):
            if p.get("_novada_fresh_session"):
                if p.get("server") == target_server:
                    self.failed_proxies.add(index)
                    logger.warning(
                        f"Прокси Novada [{index + 1}/{len(self.proxies)}] {target_server} "
                        f"(session: {target_username}) помечен как провалившийся"
                    )
                    return
            elif (
                p.get("server") == target_server
                and (p.get("username", "") or "") == target_username
                and (p.get("password", "") or "") == target_password
            ):
                self.failed_proxies.add(index)
                logger.warning(
                    f"Прокси [{index + 1}/{len(self.proxies)}] {target_server} "
                    f"(user: {target_username}) помечен как провалившийся"
                )
                return
        
        logger.debug(f"Прокси {target_server} не найден в списке для пометки как failed")

    def reset_failed_proxies(self) -> None:
        """Сбросить список провалившихся прокси."""
        self.failed_proxies.clear()
        logger.info("Список провалившихся прокси сброшен")


proxy_manager = ProxyManager()

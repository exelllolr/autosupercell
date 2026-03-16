"""
Резервные коды Google (8-значные, одноразовые).
Парсинг списка из GOOGLE_BACKUP_CODES, ротация по файлу состояния.
"""

import re
from pathlib import Path
from typing import List, Optional

from loguru import logger

from app.config import settings


def _get_state_path() -> Path:
    """Путь к файлу состояния (индекс следующего кода)."""
    path_str = getattr(
        settings, "GOOGLE_BACKUP_CODES_STATE_FILE", "data/.google_backup_code_next_index"
    )
    p = Path(path_str)
    if not p.is_absolute():
        # Относительно корня проекта (где лежит .env / запускается приложение)
        p = Path.cwd() / p
    return p


def parse_backup_codes_list(codes_str: str) -> List[str]:
    """
    Парсит строку резервных кодов в список 8-значных кодов.

    Формат: коды через запятую, в коде допустимы пробелы.
    Пример: "55192680,1234 5678, 87654321" -> ["55192680", "12345678", "87654321"]

    Args:
        codes_str: Содержимое GOOGLE_BACKUP_CODES.

    Returns:
        Список строк по 8 цифр (до 10 элементов).
    """
    if not codes_str or not codes_str.strip():
        return []
    result: List[str] = []
    # Разбиваем по запятой
    for part in codes_str.split(","):
        part = part.strip()
        digits = "".join(c for c in part if c.isdigit())
        # Каждый токен — один код (ровно 8 цифр); если в токене больше 8, берём первые 8
        if len(digits) >= 8:
            result.append(digits[:8])
        if len(result) >= 10:
            break
    return result


_codes_cache: Optional[List[str]] = None


def _get_codes_list() -> List[str]:
    """Возвращает список кодов из настроек (с кэшем)."""
    global _codes_cache
    if _codes_cache is None:
        raw = getattr(settings, "GOOGLE_BACKUP_CODES", "") or ""
        _codes_cache = parse_backup_codes_list(raw)
    return _codes_cache


def _read_next_index() -> int:
    """Читает текущий индекс из файла состояния. По умолчанию 0."""
    path = _get_state_path()
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8").strip()
        return max(0, int(text))
    except (ValueError, OSError):
        return 0


def _write_next_index(index: int) -> None:
    """Записывает индекс в файл состояния."""
    path = _get_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(index), encoding="utf-8")


def get_next_google_backup_code() -> Optional[str]:
    """
    Возвращает следующий по счёту резервный код для использования.
    Не потребляет код — потребление вызывается отдельно через consume_google_backup_code().

    Returns:
        8-значная строка кода или None, если все коды использованы.
    """
    codes = _get_codes_list()
    if not codes:
        return None
    idx = _read_next_index()
    if idx >= len(codes):
        logger.warning(
            "Все резервные коды Google использованы. Сгенерируйте новые в аккаунте Google "
            "(Security → 2-Step Verification → Backup codes) и добавьте в GOOGLE_BACKUP_CODES, "
            "затем обнулите файл состояния: {}",
            _get_state_path(),
        )
        return None
    return codes[idx]


def consume_google_backup_code() -> None:
    """
    Помечает текущий резервный код как использованный (увеличивает индекс в файле состояния).
    Вызывать один раз после успешного ввода кода в форму Google.
    """
    codes = _get_codes_list()
    if not codes:
        return
    idx = _read_next_index()
    if idx >= len(codes):
        return
    new_idx = idx + 1
    _write_next_index(new_idx)
    logger.info(
        "Резервный код Google использован (осталось {} из {}).",
        len(codes) - new_idx,
        len(codes),
    )

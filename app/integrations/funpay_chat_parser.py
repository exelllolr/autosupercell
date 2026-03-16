"""
Парсер данных из чата и заказа FunPay.

Принимает: сырой заказ (title, description) + список сообщений чата.
Возвращает: email, verification_code, email_password, game, product_name, product_type.

Логика:
  1. game + product_name  — из названия лота (regex + маппинг, fallback AI-поиск)
  2. email                — последнее сообщение покупателя, содержащее email
  3. verification_code    — последний 6-значный код из сообщений покупателя
                            (берётся максимально свежий, проверяется возраст < 5 мин)
  4. email_password       — только если явно передан в конфиге или заказе
"""

import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from loguru import logger


# ─────────────────────────── маппинги товаров ────────────────────────────────

# Ключевые слова → game slug
GAME_KEYWORDS: Dict[str, str] = {
    # Brawl Stars
    "brawl": "brawl-stars",
    "brawl stars": "brawl-stars",
    "brawl-stars": "brawl-stars",
    "бравл": "brawl-stars",
    "бравл старс": "brawl-stars",
    "bs": "brawl-stars",
    # Clash Royale
    "clash royale": "clash-royale",
    "clash-royale": "clash-royale",
    "клэш рояль": "clash-royale",
    "clash r": "clash-royale",
    "cr": "clash-royale",
    "royale": "clash-royale",
    "рояль": "clash-royale",
    # Clash of Clans
    "clash of clans": "clash-of-clans",
    "clash-of-clans": "clash-of-clans",
    "клэш оф клэнс": "clash-of-clans",
    "coc": "clash-of-clans",
    "клans": "clash-of-clans",
}

# Ключевые слова → product_type
PRODUCT_TYPE_KEYWORDS: Dict[str, str] = {
    "gems": "gems",
    "gem": "gems",
    "гем": "gems",
    "гемы": "gems",
    "гемов": "gems",
    "кристалл": "gems",
    "кристаллы": "gems",
    "gold": "gold",
    "золото": "gold",
    "pass": "pass",
    "пасс": "pass",
    "battle pass": "pass",
    "боевой пропуск": "pass",
    "cards": "cards",
    "карты": "cards",
    "wild": "wild_shards",
    "wild shards": "wild_shards",
}

# Нормализация количества гемов для product_name
GEM_COUNTS = [80, 170, 360, 950, 2000, 14000]


# ─────────────────────────── вспомогательные функции ─────────────────────────

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_OTP_RE = re.compile(r"\b(\d{6})\b")

# Шаблоны, которые выглядят как OTP, но не являются им
_OTP_EXCLUDE_RE = re.compile(
    r"^(20\d{4}|19\d{4}|202[0-9]\d{2})$"  # даты типа 202401
)


def _is_valid_otp(code: str) -> bool:
    """Проверить, что 6-значный код похож на OTP, а не на дату/случайное число."""
    if _OTP_EXCLUDE_RE.match(code):
        return False
    # Не все одинаковые цифры (111111, 000000)
    if len(set(code)) == 1:
        return False
    return True


def _parse_timestamp(ts_str: str) -> Optional[float]:
    """Преобразовать строку времени в Unix timestamp."""
    if not ts_str:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(ts_str, fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


# ─────────────────────────── основной парсер ─────────────────────────────────

class FunPayChatParser:
    """Парсер данных из заказа и чата FunPay."""

    def parse(
        self,
        order: Dict,
        messages: List[Dict],
        email_password: str = "",
    ) -> Dict:
        """
        Распарсить данные заказа.

        Args:
            order:    словарь заказа (поля: title, description, buyer_name, ...)
            messages: список сообщений чата [{author, text, is_buyer, timestamp}, ...]
            email_password: если задан — будет передан в purchase для авто-OTP

        Returns:
            {
              email:             str | None,
              verification_code: str | None,   # OTP из чата
              email_password:    str,           # пустая строка если не задан
              game:              str,
              product_name:      str,
              product_type:      str,
              otp_age_seconds:   float | None,  # возраст OTP в секундах
              errors:            list[str],     # список проблем для логирования
            }
        """
        errors: List[str] = []
        now = time.time()

        # 1. Определяем игру и товар из названия лота / описания
        source_text = " ".join([
            order.get("title", ""),
            order.get("description", ""),
        ]).lower()

        game = self._detect_game(source_text)
        product_name, product_type = self._detect_product(source_text)

        if not game:
            errors.append(f"Не удалось определить игру из: '{source_text[:80]}'")
            game = "brawl-stars"  # fallback

        if not product_name:
            errors.append(f"Не удалось определить товар из: '{source_text[:80]}'")
            product_name = "80 Gems"  # fallback
            product_type = "gems"

        # 2. Фильтруем сообщения покупателя (is_buyer=True или автор != продавец)
        buyer_messages = [m for m in messages if m.get("is_buyer", True) and not m.get("is_seller", False)]
        # Если флагов нет — берём все сообщения
        if not buyer_messages:
            buyer_messages = messages

        # 3. Ищем последний email из сообщений покупателя
        email = self._extract_last_email(buyer_messages)
        if not email:
            errors.append("Email не найден в сообщениях чата")

        # 4. Ищем последний OTP (максимально свежий)
        verification_code, otp_age = self._extract_last_otp(buyer_messages, now)

        # Предупреждение если OTP старый
        if verification_code and otp_age is not None and otp_age > 270:  # > 4.5 мин
            errors.append(
                f"OTP-код может быть просроченным (возраст {otp_age:.0f} сек). "
                "Supercell коды действуют ~5 минут."
            )

        # 5. Если OTP нет, но есть email_password — будет авто-получение
        if not verification_code and not email_password:
            errors.append(
                "Код верификации не найден в чате и email_password не задан. "
                "Автоматизация запросит покупателя прислать код."
            )

        result = {
            "email": email,
            "verification_code": verification_code,
            "email_password": email_password,
            "game": game,
            "product_name": product_name,
            "product_type": product_type,
            "otp_age_seconds": otp_age,
            "errors": errors,
        }

        logger.info(
            f"Парсер FunPay: game={game}, product={product_name}, "
            f"email={'✓' if email else '✗'}, "
            f"otp={'✓' if verification_code else '✗'}, "
            f"ошибок={len(errors)}"
        )
        return result

    # ────────────────────────── внутренние методы ────────────────────────────

    def _detect_game(self, text: str) -> Optional[str]:
        """Определить игру из текста."""
        text_lower = text.lower()

        # Сначала ищем длинные фразы (более специфичные)
        sorted_keys = sorted(GAME_KEYWORDS.keys(), key=len, reverse=True)
        for keyword in sorted_keys:
            if keyword in text_lower:
                return GAME_KEYWORDS[keyword]
        return None

    def _detect_product(self, text: str) -> Tuple[str, str]:
        """
        Определить название и тип товара из текста.

        Returns:
            (product_name, product_type)
        """
        text_lower = text.lower()

        # Определяем тип товара
        product_type = "gems"  # дефолт
        sorted_type_keys = sorted(PRODUCT_TYPE_KEYWORDS.keys(), key=len, reverse=True)
        for keyword in sorted_type_keys:
            if keyword in text_lower:
                product_type = PRODUCT_TYPE_KEYWORDS[keyword]
                break

        # Ищем количество (число + тип товара)
        # Паттерны: "80 gems", "170 гемов", "80гем", "80 gem"
        amount_patterns = [
            r"(\d+)\s*(?:gem|гем|кристалл|gold|золот|card|карт|wild)",
            r"(?:gem|гем|кристалл|gold|золот)\w*\s*(\d+)",
            r"(\d+)\s+gems?",
            r"(\d+)\s+гемов?",
        ]

        amount = None
        for pattern in amount_patterns:
            m = re.search(pattern, text_lower)
            if m:
                try:
                    amount = int(m.group(1))
                    break
                except (ValueError, IndexError):
                    continue

        # Если нашли количество — нормализуем к ближайшему стандартному
        if amount:
            if product_type == "gems":
                closest = min(GEM_COUNTS, key=lambda x: abs(x - amount))
                product_name = f"{closest} Gems"
            else:
                product_name = f"{amount} {product_type.capitalize()}"
        else:
            # Попытка найти просто число в тексте рядом с известным типом
            m = re.search(r"(\d+)", text_lower)
            if m and product_type == "gems":
                amount_raw = int(m.group(1))
                if 10 <= amount_raw <= 20000:
                    closest = min(GEM_COUNTS, key=lambda x: abs(x - amount_raw))
                    product_name = f"{closest} Gems"
                else:
                    product_name = "80 Gems"  # fallback
            else:
                product_name = "80 Gems"  # fallback

        return product_name, product_type

    def _extract_last_email(self, messages: List[Dict]) -> Optional[str]:
        """
        Извлечь последний email из сообщений.
        Берётся последнее по времени сообщение с email.
        """
        last_email = None

        # Перебираем с конца (последнее = самое свежее)
        for msg in reversed(messages):
            text = msg.get("text", "")
            matches = _EMAIL_RE.findall(text)
            if matches:
                # Берём первый найденный в этом сообщении
                candidate = matches[0].strip().lower()
                # Фильтруем: исключаем служебные адреса
                if not any(excl in candidate for excl in ("noreply", "no-reply", "example.com")):
                    last_email = candidate
                    logger.debug(f"Email найден в сообщении: {candidate}")
                    break  # нашли последний

        return last_email

    def _extract_last_otp(
        self,
        messages: List[Dict],
        now: float,
    ) -> Tuple[Optional[str], Optional[float]]:
        """
        Извлечь последний (самый свежий) OTP из сообщений.

        Returns:
            (otp_code | None, age_seconds | None)
        """
        # Перебираем с конца
        for msg in reversed(messages):
            text = msg.get("text", "")
            matches = _OTP_RE.findall(text)

            for code in reversed(matches):
                if _is_valid_otp(code):
                    # Определяем возраст
                    ts_str = msg.get("timestamp", "")
                    ts = _parse_timestamp(ts_str)
                    age = (now - ts) if ts else None

                    # Отклоняем если OTP явно устарел (> 6 мин — даём небольшой запас)
                    if age is not None and age > 360:
                        logger.debug(f"OTP {code} слишком старый ({age:.0f} сек), пропускаем")
                        continue

                    logger.debug(f"OTP найден: {code}, возраст: {age}")
                    return code, age

        return None, None


# Глобальный экземпляр
funpay_chat_parser = FunPayChatParser()
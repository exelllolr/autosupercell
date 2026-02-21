"""Модуль для получения кодов верификации из email."""

import imaplib
import email
import re
from typing import Optional
from loguru import logger
from app.config import settings


class EmailCodeReader:
    """Чтение кодов верификации из email."""

    def __init__(self, email_address: str, email_password: str, imap_server: str = None):
        """
        Инициализация читателя email.

        Args:
            email_address: Email адрес
            email_password: Пароль для email (обычный пароль или app password для Gmail)
            imap_server: IMAP сервер (по умолчанию определяется автоматически)
        """
        self.email_address = email_address
        self.email_password = email_password
        
        # Определяем IMAP сервер по домену email
        if imap_server:
            self.imap_server = imap_server
            # Пытаемся определить провайдера по домену даже при ручном указании сервера
            if "@gmail.com" in email_address.lower():
                self.provider = "gmail"
            elif "@outlook.com" in email_address.lower() or "@hotmail.com" in email_address.lower():
                self.provider = "outlook"
            elif "@yahoo.com" in email_address.lower():
                self.provider = "yahoo"
            elif "@mail.ru" in email_address.lower() or "@inbox.ru" in email_address.lower():
                self.provider = "mailru"
            elif "@yandex.ru" in email_address.lower() or "@yandex.com" in email_address.lower():
                self.provider = "yandex"
            else:
                self.provider = "unknown"
        elif "@gmail.com" in email_address.lower():
            self.imap_server = "imap.gmail.com"
            self.provider = "gmail"
        elif "@outlook.com" in email_address.lower() or "@hotmail.com" in email_address.lower():
            self.imap_server = "outlook.office365.com"
            self.provider = "outlook"
        elif "@yahoo.com" in email_address.lower():
            self.imap_server = "imap.mail.yahoo.com"
            self.provider = "yahoo"
        elif "@mail.ru" in email_address.lower() or "@inbox.ru" in email_address.lower():
            self.imap_server = "imap.mail.ru"
            self.provider = "mailru"
        elif "@yandex.ru" in email_address.lower() or "@yandex.com" in email_address.lower():
            self.imap_server = "imap.yandex.ru"
            self.provider = "yandex"
        else:
            # Для неизвестных провайдеров пробуем определить по домену
            domain = email_address.split("@")[-1].lower()
            self.imap_server = f"imap.{domain}"
            self.provider = "unknown"
            logger.info(f"Используется IMAP сервер {self.imap_server} для {email_address}")

    def get_supercell_code(self, timeout: int = 120, max_attempts: int = 12) -> Optional[str]:
        """
        Получить код верификации Supercell из email.

        Args:
            timeout: Максимальное время ожидания в секундах
            max_attempts: Максимальное количество попыток проверки

        Returns:
            Код верификации или None если не найден
        """
        try:
            logger.info(f"Подключение к IMAP серверу {self.imap_server} для {self.email_address}")
            
            # Подключаемся к IMAP серверу
            mail = imaplib.IMAP4_SSL(self.imap_server)
            mail.login(self.email_address, self.email_password)
            mail.select("inbox")

            import time
            start_time = time.time()
            attempt = 0

            while time.time() - start_time < timeout and attempt < max_attempts:
                attempt += 1
                logger.info(f"Попытка {attempt}/{max_attempts}: Поиск кода Supercell...")

                # Ищем непрочитанные письма от Supercell
                # Пробуем разные варианты поиска
                search_variants = [
                    '(UNSEEN FROM "noreply@supercell.com")',
                    '(UNSEEN FROM "supercell.com")',
                    '(UNSEEN SUBJECT "Supercell")',
                    '(UNSEEN SUBJECT "verification")',
                    '(UNSEEN SUBJECT "code")',
                    '(UNSEEN)',  # Все непрочитанные письма
                ]
                
                email_ids = []
                for search_criteria in search_variants:
                    try:
                        status, messages = mail.search(None, search_criteria)
                        if status == "OK" and messages[0]:
                            found_ids = messages[0].split()
                            email_ids.extend(found_ids)
                            if email_ids:
                                logger.info(f"Найдено {len(found_ids)} писем по критерию: {search_criteria}")
                                break
                    except Exception as e:
                        logger.debug(f"Ошибка поиска по критерию {search_criteria}: {e}")
                        continue
                
                # Убираем дубликаты
                email_ids = list(set(email_ids))

                if email_ids:
                    # Проверяем последние письма (сортируем по времени получения)
                    # Берем последние 10 писем для проверки
                    for email_id in reversed(email_ids[-10:]):
                        try:
                            status, msg_data = mail.fetch(email_id, "(RFC822)")
                            
                            if status == "OK":
                                email_body = msg_data[0][1]
                                email_message = email.message_from_bytes(email_body)
                                
                                # Проверяем отправителя
                                sender = email_message.get("From", "").lower()
                                subject = email_message.get("Subject", "").lower()
                                
                                # Ищем письма от Supercell
                                is_supercell = (
                                    "supercell" in sender or
                                    "supercell" in subject or
                                    "noreply@supercell.com" in sender
                                )
                                
                                if is_supercell or not email_ids:  # Если нет других писем, проверяем все
                                    # Получаем текст письма
                                    text_content = self._get_email_text(email_message)
                                    
                                    # Ищем код (обычно 6-значный)
                                    code = self._extract_code(text_content)
                                    
                                    if code:
                                        logger.info(f"Найден код Supercell: {code} в письме от {sender}")
                                        # Помечаем письмо как прочитанное
                                        mail.store(email_id, "+FLAGS", "\\Seen")
                                        mail.close()
                                        mail.logout()
                                        return code
                        except Exception as e:
                            logger.debug(f"Ошибка обработки письма {email_id}: {e}")
                            continue

                # Ждем перед следующей попыткой
                time.sleep(10)

            mail.close()
            mail.logout()
            logger.warning("Код Supercell не найден в email")
            return None

        except imaplib.IMAP4.error as e:
            error_msg = str(e)
            logger.error(f"Ошибка IMAP подключения: {error_msg}")
            
            # Проверяем специфичные ошибки для разных провайдеров
            if "Application-specific password required" in error_msg or ("ALERT" in error_msg and self.provider == "gmail"):
                # Только для Gmail требуется App Password при включенной 2FA
                raise Exception(
                    f"Gmail требует App Password (пароль приложения) для доступа через IMAP. "
                    f"Используйте обычный пароль, если 2FA не включена, или создайте App Password: "
                    f"https://support.google.com/accounts/answer/185833"
                )
            elif "authentication failed" in error_msg.lower() or "invalid credentials" in error_msg.lower():
                raise Exception(
                    f"Неверные учетные данные для {self.email_address}. "
                    f"Проверьте правильность email и пароля. "
                    f"Для Gmail с включенной 2FA используйте App Password."
                )
            elif "connection refused" in error_msg.lower() or "name or service not known" in error_msg.lower():
                raise Exception(
                    f"Не удалось подключиться к IMAP серверу {self.imap_server}. "
                    f"Проверьте правильность email адреса или укажите IMAP сервер вручную."
                )
            else:
                raise Exception(
                    f"Ошибка подключения к email {self.email_address}: {error_msg}. "
                    f"Проверьте правильность учетных данных и настройки IMAP."
                )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Ошибка получения кода из email: {error_msg}")
            
            # Если это уже наша кастомная ошибка, пробрасываем её дальше
            if "требует App Password" in error_msg or "Неверные учетные данные" in error_msg:
                raise
            
            raise Exception(f"Ошибка получения кода из email: {error_msg}")

    def _get_email_text(self, email_message) -> str:
        """Извлечь текст из email сообщения."""
        text_content = ""
        
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain" or content_type == "text/html":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            text_content += payload.decode("utf-8", errors="ignore")
                    except Exception:
                        pass
        else:
            try:
                payload = email_message.get_payload(decode=True)
                if payload:
                    text_content = payload.decode("utf-8", errors="ignore")
            except Exception:
                pass

        return text_content

    def _extract_code(self, text: str) -> Optional[str]:
        """
        Извлечь код верификации из текста.

        Ищет 6-значные коды, которые обычно используются Supercell.
        """
        # Паттерны для поиска кода (в порядке приоритета)
        patterns = [
            r'verification[:\s]+code[:\s]+(\d{6})',  # "verification code: 123456"
            r'code[:\s]+(\d{6})',  # "code: 123456" или "code 123456"
            r'verification[:\s]+(\d{6})',  # "verification: 123456"
            r'your[:\s]+code[:\s]+is[:\s]+(\d{6})',  # "your code is 123456"
            r'code[:\s]+is[:\s]+(\d{6})',  # "code is 123456"
            r'\b(\d{6})\b',  # 6 цифр подряд (но не в датах)
            r'(\d{6})[^\d]',  # 6 цифр с нецифровым символом после
        ]

        found_codes = []
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                for code in matches:
                    # Проверяем, что это не случайные цифры (например, дата или время)
                    if len(code) == 6 and code.isdigit():
                        # Исключаем очевидные даты (например, 202401)
                        if not (code.startswith("20") and int(code[2:4]) <= 12):
                            found_codes.append(code)
        
        if found_codes:
            # Берем первый найденный код (самый специфичный)
            code = found_codes[0]
            logger.debug(f"Извлечен код: {code} из текста (найдено {len(found_codes)} вариантов)")
            return code

        return None

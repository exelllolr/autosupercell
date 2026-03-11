"""
Отдельное логирование только действий автоматизации (клики, навигация, шаги оплаты).
Пишется в LOG_AUTOMATION_FILE (по умолчанию logs/automation.log), не смешивается с общим логом.
"""

from loguru import logger

_automation_logger = logger.bind(automation=True)


def log_automation(message: str, *args, level: str = "info", **kwargs) -> None:
    """Пишет сообщение только в файл автоматизации (logs/automation.log)."""
    getattr(_automation_logger, level.lower())(message, *args, **kwargs)

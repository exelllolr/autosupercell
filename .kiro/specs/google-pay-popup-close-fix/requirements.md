# Google Pay Popup Close Fix

## Проблема

Браузер/popup закрывается во время входа в Google Pay, вызывая ошибку:
```
Page.wait_for_timeout: Target page, context or browser has been closed
```

## Анализ логов

```
2026-03-06 16:10:56 | INFO | Ожидание поля email в payframe (до 50 сек)...
2026-03-06 16:11:08 | WARNING | Ошибка при входе в Google: Page.wait_for_timeout: Target page, context or browser has been closed
2026-03-06 16:11:08 | INFO | Подтверждение оплаты в Google Pay popup...
```

**Причина:** Popup окно закрывается во время цикла ожидания поля email (50 секунд), когда вызывается `await popup_page.wait_for_timeout(1000)`.

## Корневая причина

1. **Popup закрывается преждевременно** - Google Pay обнаруживает автоматизацию или происходит ошибка
2. **Нет обработки закрытия** - `wait_for_timeout` не обёрнут в try-except
3. **Долгий цикл ожидания** - 50 секунд ожидания поля email без проверки состояния страницы

## Требования

### FR-1: Обработка закрытия popup
- Все `wait_for_timeout` должны быть обёрнуты в try-except
- При закрытии popup должен возвращаться понятный error message
- Не должно быть необработанных исключений

### FR-2: Проверка состояния страницы
- Перед каждым `wait_for_timeout` проверять что страница не закрыта
- Использовать `page.is_closed()` для проверки

### FR-3: Логирование
- Логировать когда popup закрывается
- Логировать причину закрытия (если доступна)

## Критерии приёмки

- [ ] Нет необработанных исключений "Target page, context or browser has been closed"
- [ ] Понятное сообщение об ошибке когда popup закрывается
- [ ] Логи показывают когда и почему popup закрылся
- [ ] Graceful degradation - продолжение работы после ошибки

## Технические детали

**Файл:** `app/core/google_pay.py`

**Функция:** `_login_google_in_popup` (строки 559-900)

**Проблемные места:**
1. Строка ~750: `await popup_page.wait_for_timeout(1000)` в цикле ожидания email
2. Строка ~850: `await popup_page.wait_for_timeout(6000)` после нажатия Next
3. Другие `wait_for_timeout` без обработки

## Решение

### Вариант 1: Try-except для каждого wait_for_timeout
```python
try:
    await popup_page.wait_for_timeout(1000)
except Exception as e:
    if "closed" in str(e).lower():
        logger.warning("Popup закрылся во время ожидания")
        return False, "Popup Google Pay закрылся преждевременно"
    raise
```

### Вариант 2: Проверка is_closed перед wait
```python
if popup_page.is_closed():
    logger.warning("Popup уже закрыт")
    return False, "Popup Google Pay закрыт"
    
await popup_page.wait_for_timeout(1000)
```

### Вариант 3: Wrapper функция (РЕКОМЕНДУЕТСЯ)
```python
async def _safe_wait(page, timeout_ms):
    """Безопасное ожидание с проверкой закрытия страницы."""
    try:
        if page.is_closed():
            return False
        await page.wait_for_timeout(timeout_ms)
        return True
    except Exception as e:
        if "closed" in str(e).lower():
            logger.debug(f"Страница закрыта во время ожидания: {e}")
            return False
        raise

# Использование
if not await _safe_wait(popup_page, 1000):
    return False, "Popup закрылся"
```

## Приоритет

**CRITICAL** - Блокирует работу Google Pay flow

## Оценка

- Реализация: 1 час
- Тестирование: 30 минут
- Итого: 1.5 часа

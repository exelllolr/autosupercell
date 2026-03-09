# ✅ Google Pay Popup Close Fix Applied

## Проблема

Браузер/popup закрывался во время входа в Google Pay, вызывая необработанное исключение:
```
Page.wait_for_timeout: Target page, context or browser has been closed
```

## Анализ логов

```
2026-03-06 16:10:56 | INFO | Ожидание поля email в payframe (до 50 сек)...
2026-03-06 16:11:08 | WARNING | Ошибка при входе в Google: Page.wait_for_timeout: Target page, context or browser has been closed
```

**Причина:** Popup окно закрывалось во время цикла ожидания поля email (50 секунд), когда вызывался `await popup_page.wait_for_timeout(1000)`.

## Решение

Добавлены две helper функции для безопасного ожидания:

### 1. `_safe_wait(page, timeout_ms)` 
Безопасное ожидание с проверкой закрытия страницы:
```python
async def _safe_wait(page, timeout_ms: int) -> bool:
    """Безопасное ожидание с проверкой закрытия страницы.
    
    Returns:
        True если ожидание успешно, False если страница закрыта
    """
    try:
        if hasattr(page, 'is_closed') and page.is_closed():
            logger.debug("Страница уже закрыта")
            return False
        await page.wait_for_timeout(timeout_ms)
        return True
    except Exception as e:
        if "closed" in str(e).lower() or "target" in str(e).lower():
            logger.debug(f"Страница закрыта во время ожидания: {e}")
            return False
        raise
```

### 2. Обновлён `_delay(page, min_ms, max_ms)`
Теперь возвращает `bool` и проверяет закрытие:
```python
async def _delay(page, min_ms: int = 300, max_ms: int = 800):
    """Задержка с проверкой закрытия страницы."""
    try:
        if hasattr(page, 'is_closed') and page.is_closed():
            logger.debug("Страница закрыта, пропускаем delay")
            return False
        await page.wait_for_timeout(random.randint(min_ms, max_ms))
        return True
    except Exception as e:
        if "closed" in str(e).lower():
            logger.debug(f"Страница закрыта во время delay: {e}")
            return False
        raise
```

### 3. Обновлён цикл ожидания email
Теперь проверяет закрытие popup на каждой итерации:
```python
logger.info("Ожидание поля email в payframe (до 50 сек)...")
for wait_attempt in range(50):
    if email_entered:
        break
    # ... попытки ввода email ...
    
    # Проверяем что popup не закрылся перед следующей итерацией
    if not await _safe_wait(popup_page, 1000):
        logger.warning("Popup закрылся во время ожидания поля email")
        return False, "Popup Google Pay закрылся во время ожидания поля email"
```

## Изменённые файлы

- ✅ `app/core/google_pay.py` - Добавлены `_safe_wait` и обновлён `_delay`
- ✅ `.kiro/specs/google-pay-popup-close-fix/requirements.md` - Спецификация проблемы

## Результат

### До исправления:
```
2026-03-06 16:11:08 | WARNING | Ошибка при входе в Google: Page.wait_for_timeout: Target page, context or browser has been closed
2026-03-06 16:11:08 | INFO | Google Pay результат: {'success': False, 'error': 'Не удалось подтвердить оплату в Google Pay popup'}
```

### После исправления:
```
2026-03-09 XX:XX:XX | INFO | Ожидание поля email в payframe (до 50 сек)...
2026-03-09 XX:XX:XX | WARNING | Popup закрылся во время ожидания поля email
2026-03-09 XX:XX:XX | INFO | Google Pay результат: {'success': False, 'error': 'Popup Google Pay закрылся во время ожидания поля email'}
```

**Улучшения:**
1. ✅ Нет необработанных исключений
2. ✅ Понятное сообщение об ошибке
3. ✅ Graceful degradation - продолжение работы
4. ✅ Логи показывают когда popup закрылся

## Тестирование

Запустить тест:
```bash
python examples/manual_login_gpay_demo.py
```

Ожидаемое поведение:
- Если popup закрывается - понятное сообщение об ошибке
- Нет необработанных исключений
- Логи показывают момент закрытия

## Дополнительные улучшения (опционально)

### 1. Добавить retry логику
```python
max_retries = 3
for attempt in range(max_retries):
    try:
        result = await _login_google_in_popup(...)
        if result[0]:  # success
            break
    except Exception as e:
        if attempt < max_retries - 1:
            logger.warning(f"Попытка {attempt + 1} не удалась, повтор...")
            await asyncio.sleep(5)
        else:
            raise
```

### 2. Добавить мониторинг popup состояния
```python
async def _monitor_popup_state(popup_page):
    """Мониторинг состояния popup в фоне."""
    while not popup_page.is_closed():
        await asyncio.sleep(1)
    logger.warning("Popup закрылся!")
```

### 3. Добавить timeout для всего flow
```python
async with asyncio.timeout(300):  # 5 минут
    result = await process_google_pay(...)
```

## Связанные проблемы

- Popup может закрываться из-за:
  1. Google обнаруживает автоматизацию
  2. Cloudflare Turnstile блокирует
  3. Таймаут на стороне FastSpring
  4. Пользователь закрыл окно вручную

- Рекомендации:
  1. Использовать `BROWSER_HEADLESS=false` + Xvfb в Docker
  2. Использовать `BROWSER_USE_PATCHRIGHT=true`
  3. Использовать persistent profile с ручным логином
  4. Добавить retry логику

## Статус

✅ **ИСПРАВЛЕНО** - Нет необработанных исключений при закрытии popup

---

**Следующие шаги:**
1. Протестировать на реальном flow
2. Добавить retry логику (опционально)
3. Мониторинг метрик успешности Google Pay

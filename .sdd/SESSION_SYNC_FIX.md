# Исправление синхронизации сессии между доменами

## Проблема

На сервере (особенно через прокси) после успешной авторизации на `accounts.supercell.com` при переходе в магазин `store.supercell.com` страница показывала "Log in to view offers" вместо списка товаров.

## Причина

Сессия авторизации не успевала синхронизироваться между доменами `accounts.supercell.com` и `store.supercell.com`. Локально это происходит быстро, но на сервере через прокси требуется больше времени (до 30 секунд).

## Решение

Добавлена проверка синхронизации сессии после авторизации в `app/api/store_routes.py` (функция `_purchase_flow`):

1. После успешной авторизации переходим на главную `https://store.supercell.com`
2. Ждём до 30 секунд (6 попыток по 5 сек) пока исчезнет кнопка "Log in"
3. Исчезновение кнопки "Log in" = признак успешной синхронизации сессии
4. Делаем скриншот `store_after_auth_{session_id}.png` для диагностики
5. Только после этого переходим к поиску товара

## Код

```python
# КРИТИЧНО: После авторизации нужно дождаться синхронизации сессии между
# accounts.supercell.com и store.supercell.com
logger.info("Проверка синхронизации сессии на store.supercell.com...")
try:
    await browser.page.goto("https://store.supercell.com", wait_until="domcontentloaded", timeout=30000)
    await browser.human_like_delay(2000, 3000)
    
    # Ждём пока исчезнет кнопка "Log in" (максимум 30 сек)
    for attempt in range(6):
        try:
            login_btn = browser.page.locator('a:has-text("Log in"), button:has-text("Log in")').first
            if await login_btn.count() > 0 and await login_btn.is_visible():
                logger.info(f"Сессия ещё не синхронизирована (попытка {attempt + 1}/6), ждём...")
                await browser.human_like_delay(5000, 6000)
            else:
                logger.info("Сессия синхронизирована - кнопка Log in исчезла")
                break
        except Exception:
            logger.info("Сессия синхронизирована - кнопка Log in не найдена")
            break
    else:
        logger.warning("Сессия может быть не синхронизирована после 30 сек ожидания")
    
    await browser.take_screenshot(f"store_after_auth_{session_id}.png")
except Exception as e:
    logger.warning(f"Ошибка проверки синхронизации сессии: {e}")
```

## Результат

Теперь на сервере сценарий будет ждать полной синхронизации сессии перед поиском товаров, что устранит ошибку "Log in to view offers".

## Дата

2026-03-07

# Реализация детального логирования - Summary

## Что сделано

### 1. Добавлено логирование сетевых запросов
✅ `_setup_network_logging()` в `BrowserAutomation`
- Логирует все HTTP requests/responses
- Фильтрует шум (fonts, analytics, ads)
- Выделяет ошибки (4xx, 5xx) и redirects (3xx)
- Собирает статистику failed requests

### 2. Добавлено логирование консоли браузера
✅ `_setup_console_logging()` в `BrowserAutomation`
- Логирует console.error, console.warning
- Ловит uncaught exceptions на странице
- Фильтрует шум (favicon, DevTools)

### 3. Проверка viewport и разрешения
✅ `_check_viewport_consistency()` в `BrowserAutomation`
- Проверяет соответствие текущего viewport заданному
- Логирует device pixel ratio
- Детектирует изменения размера окна

### 4. Детекция iframe
✅ `_detect_iframes()` в `BrowserAutomation`
- Находит все iframe на странице
- Проверяет доступность (same-origin policy)
- Логирует src, id, размеры, видимость
- Показывает все frames (main + iframes)

### 5. Комплексная диагностика
✅ `_log_diagnostics()` в `BrowserAutomation`
- Объединяет все проверки в одном вызове
- Показывает URL, viewport, iframes, network stats
- Вызывается автоматически в критичных точках

### 6. Интеграция в flow
✅ Добавлены вызовы диагностики в `store_routes.py`:
- `after_browser_start` - после запуска браузера
- `after_auth` - после авторизации
- `after_goto_store` - после перехода на store
- `before_purchase_flow` - перед покупкой
- `after_navigate_to_store` - после навигации в магазин
- `before_product_search` - перед поиском товара

### 7. Конфигурация
✅ Добавлены переменные в `.env.example`:
```bash
BROWSER_NETWORK_LOG=true
BROWSER_CONSOLE_LOG=true
```

## Изменённые файлы

1. `app/core/browser_automation.py`
   - Добавлены поля в `__init__`: `network_log_enabled`, `console_log_enabled`, `request_count`, `failed_requests`
   - Новые методы: `_setup_network_logging()`, `_setup_console_logging()`, `_check_viewport_consistency()`, `_detect_iframes()`, `_log_diagnostics()`
   - Вызовы setup в методе `start()`

2. `app/api/store_routes.py`
   - Добавлены вызовы `browser._log_diagnostics()` в критичных точках

3. `.env.example`
   - Добавлены `BROWSER_NETWORK_LOG` и `BROWSER_CONSOLE_LOG`

## Как использовать

### Включить логирование
```bash
# В .env
BROWSER_NETWORK_LOG=true
BROWSER_CONSOLE_LOG=true
```

### Анализ логов на сервере
```bash
# Все ошибки сети
docker-compose logs autosupercell-app | grep "ERROR\|FAILED"

# Viewport проблемы
docker-compose logs autosupercell-app | grep "VIEWPORT MISMATCH"

# Iframe детекция
docker-compose logs autosupercell-app | grep "IFRAMES detected"

# Комплексная диагностика
docker-compose logs autosupercell-app | grep "=== DIAGNOSTICS"
```

## Что это даёт

### Для диагностики проблемы "Log in to view offers"
1. **Сетевые запросы** - видим все API calls к store.supercell.com
2. **Redirects** - видим куда перенаправляет после авторизации
3. **Failed requests** - видим что не загружается (товары, API)
4. **Console errors** - видим CSP, CORS, mixed content ошибки
5. **Viewport** - проверяем что разрешение не меняется
6. **Iframe** - детектируем payment frames, recaptcha

### Пример вывода
```
=== DIAGNOSTICS after_goto_store ===
URL: https://store.supercell.com
Viewport OK after_goto_store: 1920x1080 (dpr: 1)
IFRAMES detected after_goto_store: 0 iframe(s)
Page frames count: 1 (main + iframes)
  Frame[0]: MAIN - https://store.supercell.com
Network: 23 requests, 0 failed
=== END DIAGNOSTICS ===

→ [GET] https://store.supercell.com/api/products
← [200] GET https://store.supercell.com/api/products
```

## Производительность

- Минимальная нагрузка (async listeners)
- Фильтрация шума (fonts, analytics)
- Диагностика только в критичных точках (5-6 раз за сессию)

## Следующие шаги

1. Запустить на сервере с `BROWSER_NETWORK_LOG=true`
2. Воспроизвести проблему "Log in to view offers"
3. Проанализировать логи:
   - Какие запросы failed?
   - Есть ли redirects после авторизации?
   - Загружаются ли товары через API?
   - Есть ли console errors?
4. На основе логов определить root cause

## Дата
2026-03-07

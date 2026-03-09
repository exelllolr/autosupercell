# Использование детального логирования

## Включение логирования

Добавь в `.env`:

```bash
# Детальное логирование сети и консоли
BROWSER_NETWORK_LOG=true
BROWSER_CONSOLE_LOG=true
```

## Что логируется

### 1. Сетевые запросы

**DEBUG уровень** - все успешные запросы:
```
→ [GET] https://store.supercell.com/api/products
← [200] GET https://store.supercell.com/api/products
```

**WARNING уровень** - redirects:
```
← [302] REDIRECT GET https://accounts.supercell.com/login
```

**ERROR уровень** - ошибки:
```
← [404] CLIENT ERROR GET https://store.supercell.com/missing
← [500] SERVER ERROR POST https://api.example.com/endpoint
✗ [GET] FAILED https://cdn.example.com/script.js - net::ERR_CONNECTION_REFUSED
```

### 2. Console messages

**ERROR** - ошибки JavaScript:
```
CONSOLE ERROR: Uncaught TypeError: Cannot read property 'x' of undefined
PAGE ERROR (uncaught exception): ReferenceError: foo is not defined
```

**WARNING** - предупреждения:
```
CONSOLE WARNING: Mixed Content: The page at 'https://...' was loaded over HTTPS, but requested an insecure resource
```

### 3. Viewport и разрешение

```
Viewport OK after_auth: 1920x1080 (dpr: 1)
VIEWPORT MISMATCH after_goto_store: expected 1920x1080, actual 1366x768 (outer: 1366x768, dpr: 1)
```

### 4. Iframe детекция

```
IFRAMES detected after_navigate_to_store: 2 iframe(s)
  - iframe[0]: src=https://pay.fastspring.com/checkout, id=payment-frame, visible=true, size=800x600
  - iframe[1]: src=https://www.google.com/recaptcha/api2/anchor, id=, visible=false, size=0x0
Page frames count: 3 (main + iframes)
  Frame[0]: MAIN - https://store.supercell.com/clashroyale
  Frame[1]: IFRAME - https://pay.fastspring.com/checkout
  Frame[2]: inaccessible (cross-origin?) - SecurityError: Blocked a frame with origin...
```

### 5. Комплексная диагностика

В критичных точках вызывается `_log_diagnostics()`:

```
=== DIAGNOSTICS after_auth ===
URL: https://accounts.supercell.com/login
Viewport OK after_auth: 1920x1080 (dpr: 1)
IFRAMES detected after_auth: 0 iframe(s)
Page frames count: 1 (main + iframes)
  Frame[0]: MAIN - https://accounts.supercell.com/login
Network: 47 requests, 2 failed
Failed requests: [{'url': 'https://cdn.example.com/script.js', 'error': 'net::ERR_CONNECTION_REFUSED', 'method': 'GET'}]
=== END DIAGNOSTICS ===
```

## Точки диагностики

Диагностика вызывается автоматически в:

1. `after_browser_start` - после запуска браузера
2. `after_auth` - после успешной авторизации
3. `after_goto_store` - после перехода на store.supercell.com
4. `before_purchase_flow` - перед началом покупки
5. `after_navigate_to_store` - после перехода в магазин игры
6. `before_product_search` - перед поиском товара

## Фильтрация шума

Автоматически фильтруются:
- Шрифты (.woff2, .ttf, .eot)
- Analytics (google-analytics, googletagmanager)
- Реклама (doubleclick, googlesyndication)
- Facebook pixel
- Изображения (.png, .jpg, .svg, .ico) - опционально

## Анализ логов на сервере

```bash
# Все ошибки сети
docker-compose logs autosupercell-app | grep "CLIENT ERROR\|SERVER ERROR\|FAILED"

# Все redirects
docker-compose logs autosupercell-app | grep "REDIRECT"

# Viewport проблемы
docker-compose logs autosupercell-app | grep "VIEWPORT MISMATCH"

# Iframe детекция
docker-compose logs autosupercell-app | grep "IFRAMES detected"

# Console errors
docker-compose logs autosupercell-app | grep "CONSOLE ERROR\|PAGE ERROR"

# Комплексная диагностика
docker-compose logs autosupercell-app | grep "=== DIAGNOSTICS"
```

## Отключение логирования

Если логи создают слишком много шума:

```bash
# Отключить network logging
BROWSER_NETWORK_LOG=false

# Отключить console logging
BROWSER_CONSOLE_LOG=false
```

## Производительность

Логирование добавляет минимальную нагрузку:
- Network listeners - async, не блокируют запросы
- Console listeners - async, не блокируют рендеринг
- Диагностика - вызывается только в критичных точках (5-6 раз за сессию)

Рекомендуется держать включённым на сервере для диагностики проблем.

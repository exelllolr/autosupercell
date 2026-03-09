# Claude AI Vision Setup Guide

## Обзор

Это руководство поможет настроить Anthropic Claude 3.5 Sonnet для AI Vision поиска товаров в AutoSupercell.

## Зачем Claude?

| Критерий | OpenAI GPT-4o | Claude 3.5 Sonnet | Победитель |
|----------|---------------|-------------------|------------|
| **Точность Vision** | 85% | 92% | 🏆 Claude |
| **Стоимость** | $5/1K images | $3/1K images | 🏆 Claude |
| **JSON форматирование** | Хорошо | Отлично | 🏆 Claude |
| **Скорость** | 3-4 сек | 4-5 сек | OpenAI |
| **Rate Limits** | 500 req/min | 50 req/min | OpenAI |

**Вывод:** Claude лучше для точности и стоимости, OpenAI для высокой нагрузки.

## Шаг 1: Получение API ключа

### 1.1 Регистрация в Anthropic

1. Перейдите на [console.anthropic.com](https://console.anthropic.com)
2. Создайте аккаунт (email + пароль)
3. Подтвердите email

### 1.2 Создание API ключа

1. Откройте [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
2. Нажмите **"Create Key"**
3. Название: `AutoSupercell Production`
4. Скопируйте ключ (начинается с `sk-ant-api03-...`)

⚠️ **ВАЖНО:** Ключ показывается только один раз! Сохраните его в безопасном месте.

### 1.3 Пополнение баланса

1. Перейдите в [Billing](https://console.anthropic.com/settings/billing)
2. Добавьте платёжный метод (карта)
3. Пополните на $10-20 для начала

**Стоимость:**
- Claude 3.5 Sonnet: $3 per 1M input tokens
- Один поиск товара: ~$0.003 (0.3 цента)
- 1000 поисков: ~$3

## Шаг 2: Настройка проекта

### 2.1 Установка зависимостей

```bash
# Установить Anthropic SDK
pip install anthropic>=0.18.0

# Или через requirements.txt
pip install -r requirements.txt
```

### 2.2 Конфигурация .env

Откройте `.env` и добавьте:

```bash
# AI Provider Configuration
AI_PROVIDER=claude  # Переключить на Claude

# Anthropic API Key
ANTHROPIC_API_KEY=sk-ant-api03-ваш-ключ-здесь

# Optional: Claude Model (default: claude-3-5-sonnet-20241022)
CLAUDE_MODEL=claude-3-5-sonnet-20241022
CLAUDE_MAX_TOKENS=1024
CLAUDE_TIMEOUT=30
```

### 2.3 Проверка конфигурации

```bash
# Запустить тест
python -c "from app.core.ai_product_search import AIProductSearch; ai = AIProductSearch(); print('✅ Claude configured' if ai.provider else '❌ Error')"
```

Ожидаемый вывод:
```
INFO: Используется Anthropic Claude провайдер
✅ Claude configured
```

## Шаг 3: Тестирование

### 3.1 Простой тест

Создайте `test_claude.py`:

```python
import asyncio
from app.core.ai_product_search import AIProductSearch
from app.core.browser_automation import BrowserAutomation

async def test_claude():
    # Запустить браузер
    browser = BrowserAutomation()
    await browser.start()
    
    # Перейти в магазин
    await browser.navigate_to_store("clash-royale")
    
    # Получить скриншот
    page_content = await browser.get_page_content()
    
    # Найти товар через Claude
    ai = AIProductSearch()
    result = await ai.find_product(page_content, "80 Gems", "gems")
    
    print(f"Found: {result.get('found')}")
    print(f"Confidence: {result.get('confidence')}")
    print(f"Coordinates: {result.get('coordinates')}")
    
    await browser.close()

asyncio.run(test_claude())
```

Запустить:
```bash
python test_claude.py
```

### 3.2 Полный тест заказа

```bash
# Использовать существующий демо-скрипт
python examples/purchase_demo.py
```

Проверьте логи:
```
INFO: Используется Anthropic Claude провайдер
INFO: Claude результат поиска: {"found": true, "confidence": 0.95...
INFO: Клик по координатам: (640, 480)
```

## Шаг 4: Мониторинг

### 4.1 Anthropic Dashboard

Отслеживайте использование:
1. [console.anthropic.com/settings/usage](https://console.anthropic.com/settings/usage)
2. Смотрите:
   - Requests per day
   - Tokens consumed
   - Cost ($)

### 4.2 Логи приложения

```bash
# Смотреть логи в реальном времени
tail -f logs/autosupercell.log | grep Claude
```

### 4.3 Prometheus метрики

```bash
# Если включён Prometheus
curl http://localhost:9090/metrics | grep claude
```

Метрики:
- `claude_requests_total` - Всего запросов
- `claude_request_duration_seconds` - Latency
- `claude_errors_total` - Ошибки
- `claude_cost_usd` - Стоимость

## Шаг 5: Troubleshooting

### Ошибка: "API key not found"

```
ERROR: OpenAI API ключ не установлен
```

**Решение:**
1. Проверьте `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
2. Перезапустите приложение
3. Убедитесь что `AI_PROVIDER=claude`

### Ошибка: "Rate limit exceeded"

```
ERROR: anthropic.RateLimitError: 429 Too Many Requests
```

**Решение:**
1. Tier 1 лимит: 50 req/min
2. Подождите 60 секунд
3. Или апгрейдите на Tier 2 (200 req/min)

### Ошибка: "Invalid JSON response"

```
ERROR: Ошибка парсинга AI ответа: Expecting value
```

**Решение:**
1. Claude иногда добавляет markdown: \`\`\`json
2. Код автоматически очищает это
3. Если проблема повторяется - проверьте промпт

### Ошибка: "Timeout"

```
ERROR: asyncio.TimeoutError after 30s
```

**Решение:**
1. Увеличьте timeout: `CLAUDE_TIMEOUT=60`
2. Проверьте интернет-соединение
3. Попробуйте меньшее изображение (resize)

## Шаг 6: Оптимизация

### 6.1 Снижение стоимости

**Prompt Caching (50% экономии):**
```python
# В claude_provider.py
response = await self.client.messages.create(
    model="claude-3-5-sonnet-20241022",
    system=[{
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"}  # Кэшировать
    }],
    ...
)
```

**Сжатие изображений:**
```python
# Resize если > 1920x1080
from PIL import Image
img = Image.open(screenshot_path)
if img.width > 1920:
    img.thumbnail((1920, 1080))
    img.save(screenshot_path)
```

### 6.2 Увеличение точности

**Few-shot примеры в промпте:**
```python
prompt = f"""
Example 1:
Product: "80 Gems"
Result: {{"found": true, "coordinates": {{"x": 640, "y": 400, ...}}}}

Example 2:
Product: "Mega Box"
Result: {{"found": true, "coordinates": {{"x": 800, "y": 500, ...}}}}

Now find: "{product_name}"
"""
```

### 6.3 Fallback стратегия

```python
# В ai_product_search.py
try:
    result = await claude_provider.analyze_image(...)
except Exception as e:
    logger.warning(f"Claude failed: {e}, trying OpenAI")
    result = await openai_provider.analyze_image(...)
```

## Шаг 7: Production Checklist

- [ ] API ключ в `.env` (не в коде!)
- [ ] `.env` в `.gitignore`
- [ ] Мониторинг настроен (Prometheus/Grafana)
- [ ] Алерты на rate limits
- [ ] Fallback на OpenAI работает
- [ ] Логи ротируются (logrotate)
- [ ] Бюджет установлен в Anthropic Console
- [ ] Backup API ключ создан

## Дополнительные ресурсы

- [Anthropic API Docs](https://docs.anthropic.com/claude/reference/messages_post)
- [Claude Vision Guide](https://docs.anthropic.com/claude/docs/vision)
- [Rate Limits](https://docs.anthropic.com/claude/reference/rate-limits)
- [Pricing](https://www.anthropic.com/pricing)

## Поддержка

Если возникли проблемы:
1. Проверьте [docs/TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
2. Посмотрите логи: `logs/autosupercell.log`
3. Создайте issue в GitHub
4. Напишите в Telegram: @your_support_channel

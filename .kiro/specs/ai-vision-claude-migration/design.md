# Design: AI Vision Migration to Claude

## Архитектура

### Текущая архитектура
```
OrderProcessor
    ↓
AIProductSearch
    ↓
OpenAIProvider (gpt-4o)
    ↓
Playwright Screenshot → Base64 → OpenAI API → JSON
```

### Новая архитектура
```
OrderProcessor
    ↓
AIProductSearch
    ↓
    ├─→ ClaudeProvider (primary) ──→ Anthropic API
    ├─→ OpenAIProvider (fallback) ──→ OpenAI API
    └─→ CSSFallback (last resort) ──→ Direct DOM
```

## Компоненты

### 1. ClaudeProvider

**Файл:** `app/core/ai_providers/claude_provider.py`

**Интерфейс:**
```python
class ClaudeProvider(BaseAIProvider):
    def __init__(self):
        self.api_key: str
        self.client: AsyncAnthropic
        self.model: str = "claude-3-5-sonnet-20241022"
        
    def is_available(self) -> bool:
        """Проверка наличия API ключа"""
        
    async def analyze_image(
        self, 
        image_path: str, 
        prompt: str
    ) -> Optional[str]:
        """Анализ изображения через Claude Vision API"""
```

**Особенности:**
- Использует `anthropic` SDK (не `openai`)
- System prompt отдельно от user prompt
- Поддержка prompt caching для экономии
- Retry логика с exponential backoff

### 2. AIProductSearch (обновление)

**Файл:** `app/core/ai_product_search.py`

**Изменения:**
```python
class AIProductSearch:
    def _get_provider(self) -> Optional[BaseAIProvider]:
        """
        Приоритет провайдеров:
        1. Claude (если AI_PROVIDER=claude)
        2. OpenAI (если AI_PROVIDER=openai)
        3. Gemini (если AI_PROVIDER=gemini)
        """
        
    async def find_product(
        self, 
        page_content: Dict, 
        product_name: str, 
        product_type: str = "gems"
    ) -> Optional[Dict]:
        """
        Добавить fallback chain:
        1. Попытка через primary provider (Claude)
        2. Если ошибка → fallback на OpenAI
        3. Если оба не работают → CSS селекторы
        """
```

### 3. Конфигурация

**Файл:** `app/config.py`

**Добавить:**
```python
class Settings(BaseSettings):
    # AI Providers
    AI_PROVIDER: str = "claude"  # openai, claude, gemini
    ANTHROPIC_API_KEY: str = ""
    
    # Claude specific
    CLAUDE_MODEL: str = "claude-3-5-sonnet-20241022"
    CLAUDE_MAX_TOKENS: int = 1024
    CLAUDE_TIMEOUT: int = 30
    CLAUDE_ENABLE_CACHING: bool = True
```

## Промпт-инжиниринг

### System Prompt (Claude)
```python
CLAUDE_SYSTEM_PROMPT = """You are a precise computer vision assistant specialized in finding UI elements on game store screenshots.

Your task: Locate products in Supercell Store interfaces and return exact coordinates.

CRITICAL RULES:
1. Respond ONLY with valid JSON (no markdown, no explanations)
2. Coordinates are in pixels from top-left corner (0,0)
3. If product not found, return {"found": false}
4. Confidence must be 0.0-1.0 (use 0.9+ only if very certain)
5. Button text must be exact text visible on the buy button

JSON Schema:
{
  "found": boolean,
  "coordinates": {"x": number, "y": number, "width": number, "height": number},
  "button_text": string,
  "price": string | null,
  "confidence": number,
  "description": string
}"""
```

### User Prompt Template
```python
def _build_search_prompt_claude(
    self, 
    product_name: str, 
    product_type: str, 
    page_content: Dict
) -> str:
    visible_texts = [
        elem["text"][:100] 
        for elem in page_content.get("visible_elements", [])[:20]
    ]
    
    return f"""Find product "{product_name}" (type: {product_type}) on this Supercell Store screenshot.

Context - Visible text elements on page:
{chr(10).join(visible_texts)}

Task: Locate the product card and return its coordinates.

Important:
- Look for product name, price, and buy button
- Coordinates must be center of the product card
- Width/height should cover the entire card
- If multiple matches, choose the most prominent one

Return JSON only (no markdown):"""
```

## Обработка ошибок

### Retry Strategy
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        asyncio.TimeoutError
    ))
)
async def _call_claude_with_retry(self, ...):
    """Вызов Claude с автоматическими повторами"""
```

### Fallback Chain
```python
async def find_product_with_fallback(
    self, 
    page_content: Dict, 
    product_name: str
) -> Optional[Dict]:
    """
    1. Try Claude (primary)
    2. If Claude fails → try OpenAI
    3. If both fail → try CSS selectors
    4. If all fail → return None
    """
    try:
        result = await self._try_claude(...)
        if result and result.get("found"):
            return result
    except Exception as e:
        logger.warning(f"Claude failed: {e}, trying OpenAI")
        
    try:
        result = await self._try_openai(...)
        if result and result.get("found"):
            return result
    except Exception as e:
        logger.warning(f"OpenAI failed: {e}, trying CSS")
        
    return await self._try_css_fallback(...)
```

## Оптимизации

### 1. Prompt Caching
```python
# Кэшировать system prompt (экономия 50%)
response = await self.client.messages.create(
    model=self.model,
    system=[{
        "type": "text",
        "text": CLAUDE_SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"}  # Cache for 5 min
    }],
    messages=[...],
    max_tokens=self.max_tokens
)
```

### 2. Image Compression
```python
def _optimize_image(self, image_path: Path) -> Path:
    """
    Сжать изображение если > 5MB или > 1920x1080
    """
    img = Image.open(image_path)
    
    # Resize if too large
    if img.width > 1920 or img.height > 1080:
        img.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
        
    # Compress if > 5MB
    if image_path.stat().st_size > 5 * 1024 * 1024:
        img.save(image_path, optimize=True, quality=85)
        
    return image_path
```

### 3. Response Caching
```python
# Кэшировать результаты для одинаковых товаров
from functools import lru_cache

@lru_cache(maxsize=100)
def _get_cached_result(
    self, 
    product_name: str, 
    screenshot_hash: str
) -> Optional[Dict]:
    """Кэш результатов на 5 минут"""
```

## Мониторинг

### Метрики (Prometheus)
```python
# app/monitoring/metrics.py

claude_requests_total = Counter(
    'claude_requests_total',
    'Total Claude API requests',
    ['status']  # success, error, timeout
)

claude_request_duration = Histogram(
    'claude_request_duration_seconds',
    'Claude API request duration'
)

claude_cost_usd = Counter(
    'claude_cost_usd',
    'Estimated Claude API cost in USD'
)

claude_accuracy = Gauge(
    'claude_accuracy_rate',
    'Claude product detection accuracy'
)
```

### Логирование
```python
logger.info(
    f"Claude Vision: product={product_name}, "
    f"found={result['found']}, "
    f"confidence={result.get('confidence', 0):.2f}, "
    f"latency={duration:.2f}s, "
    f"cost=${cost:.4f}"
)
```

## Тестирование

### Unit Tests
```python
# tests/test_claude_provider.py

@pytest.mark.asyncio
async def test_claude_provider_initialization():
    """Тест инициализации провайдера"""
    provider = ClaudeProvider()
    assert provider.is_available()
    assert provider.model == "claude-3-5-sonnet-20241022"

@pytest.mark.asyncio
async def test_claude_analyze_image():
    """Тест анализа изображения"""
    provider = ClaudeProvider()
    result = await provider.analyze_image(
        "tests/fixtures/clash_royale_gems.png",
        "Find 80 Gems product"
    )
    assert result is not None
    assert "found" in result

@pytest.mark.asyncio
async def test_claude_json_parsing():
    """Тест парсинга JSON ответа"""
    response = '```json\n{"found": true}\n```'
    parsed = _parse_claude_response(response)
    assert parsed["found"] is True
```

### Integration Tests
```python
# tests/test_ai_search_integration.py

@pytest.mark.asyncio
async def test_find_product_with_claude():
    """Интеграционный тест поиска товара"""
    browser = BrowserAutomation()
    await browser.start()
    await browser.navigate_to_store("clash-royale")
    
    page_content = await browser.get_page_content()
    
    ai = AIProductSearch()
    result = await ai.find_product(page_content, "80 Gems", "gems")
    
    assert result is not None
    assert result["found"] is True
    assert result["confidence"] > 0.8
    
    await browser.close()
```

## Миграция

### Этап 1: Добавление Claude (без breaking changes)
1. Установить `anthropic` SDK
2. Создать `ClaudeProvider`
3. Добавить в `_get_provider()` логику выбора
4. Оставить OpenAI как default

### Этап 2: Тестирование
1. Запустить unit tests
2. Запустить integration tests
3. Ручное тестирование на staging
4. A/B тест: 50% Claude, 50% OpenAI

### Этап 3: Rollout
1. Включить Claude для 10% трафика
2. Мониторинг метрик (accuracy, latency, cost)
3. Постепенно увеличивать до 100%
4. Оставить OpenAI как fallback

### Этап 4: Оптимизация
1. Включить prompt caching
2. Добавить image compression
3. Настроить CSS fallback
4. Оптимизировать промпты

## Безопасность

### API Key Management
```python
# Никогда не логировать ключ
logger.info(f"Using Claude with key: {api_key[:8]}...")  # ❌ BAD

# Правильно
logger.info("Using Claude provider")  # ✅ GOOD
```

### Rate Limiting
```python
from aiolimiter import AsyncLimiter

# Tier 1: 50 req/min
rate_limiter = AsyncLimiter(50, 60)

async def call_claude_with_limit(self, ...):
    async with rate_limiter:
        return await self.client.messages.create(...)
```

## Rollback Plan

Если Claude не работает:

1. **Быстрый rollback:**
   ```bash
   # В .env
   AI_PROVIDER=openai  # Вернуться на OpenAI
   ```

2. **Автоматический fallback:**
   ```python
   # Уже реализовано в коде
   try:
       result = await claude_provider.analyze_image(...)
   except Exception:
       result = await openai_provider.analyze_image(...)
   ```

3. **Feature flag:**
   ```python
   ENABLE_CLAUDE = os.getenv("ENABLE_CLAUDE", "true") == "true"
   
   if ENABLE_CLAUDE:
       provider = ClaudeProvider()
   else:
       provider = OpenAIProvider()
   ```

## Документация

### Файлы для обновления:
1. ✅ `docs/CLAUDE_SETUP.md` - Инструкция по настройке
2. ✅ `.claude` - Конфигурация проекта
3. 📝 `AI_PROVIDERS_COMPARISON.md` - Сравнение провайдеров
4. 📝 `README.md` - Обновить секцию AI Vision
5. 📝 `.env.example` - Добавить ANTHROPIC_API_KEY

## Критерии готовности

- [ ] ClaudeProvider реализован и протестирован
- [ ] Fallback на OpenAI работает
- [ ] Unit tests покрывают 80%+ кода
- [ ] Integration tests проходят
- [ ] Документация обновлена
- [ ] Метрики настроены
- [ ] A/B тест показывает улучшение accuracy
- [ ] Стоимость снижена на 30%+
- [ ] Latency < 5 сек (95 перцентиль)

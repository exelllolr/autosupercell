# Tasks: AI Vision Migration to Claude

## Фаза 1: Подготовка (30 мин)

- [x] 1.1 Добавить поля в app/config.py (ВЫПОЛНЕНО)
  - CLAUDE_MODEL, CLAUDE_MAX_TOKENS, CLAUDE_TIMEOUT
  - CLAUDE_ENABLE_CACHING
  - BROWSER_NETWORK_LOG, BROWSER_CONSOLE_LOG

- [x] 1.2 Обновить .env.example (ВЫПОЛНЕНО)
  - Добавлены Claude настройки
  - Исправлены store URLs

- [ ] 1.3 Установить anthropic SDK
  ```bash
  pip install anthropic>=0.18.0
  pip install tenacity  # для retry логики
  ```

- [ ] 1.4 Обновить requirements.txt
  ```txt
  anthropic>=0.18.0
  tenacity>=8.2.0
  ```

## Фаза 2: Реализация ClaudeProvider (2 часа)

- [ ] 2.1 Создать app/core/ai_providers/claude_provider.py
  - [ ] 2.1.1 Импорты и базовая структура класса
  - [ ] 2.1.2 Метод __init__ с инициализацией AsyncAnthropic
  - [ ] 2.1.3 Метод is_available()
  - [ ] 2.1.4 Метод analyze_image() с base64 encoding
  - [ ] 2.1.5 System prompt для Claude
  - [ ] 2.1.6 Обработка ответа и парсинг JSON

- [ ] 2.2 Добавить retry логику
  ```python
  from tenacity import retry, stop_after_attempt, wait_exponential
  
  @retry(
      stop=stop_after_attempt(3),
      wait=wait_exponential(multiplier=1, min=2, max=10)
  )
  async def _call_claude_with_retry(self, ...):
  ```

- [ ] 2.3 Добавить обработку ошибок
  - [ ] 2.3.1 RateLimitError → retry
  - [ ] 2.3.2 APIConnectionError → retry
  - [ ] 2.3.3 TimeoutError → fallback
  - [ ] 2.3.4 InvalidRequestError → log + return None

- [ ] 2.4 Добавить логирование
  ```python
  logger.info(f"Claude Vision: latency={duration:.2f}s, tokens={usage}")
  ```

## Фаза 3: Интеграция в AIProductSearch (1 час)

- [ ] 3.1 Обновить app/core/ai_product_search.py
  - [ ] 3.1.1 Импортировать ClaudeProvider
  - [ ] 3.1.2 Обновить _get_provider() для поддержки Claude
  - [ ] 3.1.3 Добавить специальный промпт для Claude (_build_search_prompt_claude)

- [ ] 3.2 Реализовать fallback chain
  ```python
  async def find_product_with_fallback(self, ...):
      # 1. Try Claude
      # 2. If fails → OpenAI
      # 3. If fails → CSS selectors
  ```

- [ ] 3.3 Добавить метрики
  - [ ] 3.3.1 claude_requests_total
  - [ ] 3.3.2 claude_request_duration_seconds
  - [ ] 3.3.3 claude_errors_total

## Фаза 4: Оптимизации (1 час)

- [ ] 4.1 Prompt Caching
  ```python
  system=[{
      "type": "text",
      "text": SYSTEM_PROMPT,
      "cache_control": {"type": "ephemeral"}
  }]
  ```

- [ ] 4.2 Image Compression
  - [ ] 4.2.1 Создать _optimize_image() метод
  - [ ] 4.2.2 Resize если > 1920x1080
  - [ ] 4.2.3 Compress если > 5MB

- [ ] 4.3 Response Caching (опционально)
  ```python
  @lru_cache(maxsize=100)
  def _get_cached_result(product_name, screenshot_hash):
  ```

## Фаза 5: Тестирование (2 часа)

- [ ] 5.1 Unit Tests (tests/test_claude_provider.py)
  - [ ] 5.1.1 test_claude_provider_initialization
  - [ ] 5.1.2 test_claude_is_available
  - [ ] 5.1.3 test_claude_analyze_image
  - [ ] 5.1.4 test_claude_json_parsing
  - [ ] 5.1.5 test_claude_error_handling
  - [ ] 5.1.6 test_claude_retry_logic

- [ ] 5.2 Integration Tests (tests/test_ai_search_integration.py)
  - [ ] 5.2.1 test_find_product_with_claude
  - [ ] 5.2.2 test_fallback_to_openai
  - [ ] 5.2.3 test_confidence_threshold
  - [ ] 5.2.4 test_coordinate_accuracy

- [ ] 5.3 Ручное тестирование
  - [ ] 5.3.1 Clash Royale: найти "80 Gems"
  - [ ] 5.3.2 Brawl Stars: найти "Mega Box"
  - [ ] 5.3.3 Проверить fallback при отключении Claude
  - [ ] 5.3.4 Проверить rate limiting

- [ ] 5.4 Запустить полный тест заказа
  ```bash
  python examples/purchase_demo.py
  ```

## Фаза 6: Документация (1 час)

- [ ] 6.1 Обновить AI_PROVIDERS_COMPARISON.md
  - [ ] 6.1.1 Добавить Claude в таблицу сравнения
  - [ ] 6.1.2 Обновить рекомендации

- [ ] 6.2 Обновить README.md
  - [ ] 6.2.1 Секция "AI Vision"
  - [ ] 6.2.2 Инструкция по настройке Claude
  - [ ] 6.2.3 Примеры использования

- [ ] 6.3 Создать MIGRATION_GUIDE.md
  - [ ] 6.3.1 Как мигрировать с OpenAI на Claude
  - [ ] 6.3.2 Rollback план
  - [ ] 6.3.3 Troubleshooting

## Фаза 7: Мониторинг и Rollout (опционально)

- [ ] 7.1 Настроить Grafana dashboard
  - [ ] 7.1.1 Claude requests per minute
  - [ ] 7.1.2 Latency percentiles (p50, p95, p99)
  - [ ] 7.1.3 Error rate
  - [ ] 7.1.4 Cost tracking

- [ ] 7.2 Настроить алерты
  - [ ] 7.2.1 Error rate > 5%
  - [ ] 7.2.2 Latency p95 > 10s
  - [ ] 7.2.3 Rate limit exceeded

- [ ] 7.3 A/B тест
  - [ ] 7.3.1 50% трафика на Claude
  - [ ] 7.3.2 50% трафика на OpenAI
  - [ ] 7.3.3 Сравнить accuracy, latency, cost
  - [ ] 7.3.4 Принять решение о rollout

## Критерии завершения

✅ Все задачи выполнены
✅ Unit tests проходят (coverage > 80%)
✅ Integration tests проходят
✅ Ручное тестирование успешно
✅ Документация обновлена
✅ Метрики настроены
✅ Fallback работает корректно

## Оценка времени

| Фаза | Время |
|------|-------|
| 1. Подготовка | 30 мин |
| 2. ClaudeProvider | 2 часа |
| 3. Интеграция | 1 час |
| 4. Оптимизации | 1 час |
| 5. Тестирование | 2 часа |
| 6. Документация | 1 час |
| **Итого** | **7.5 часов** |

## Приоритеты

**Must Have (P0):**
- ClaudeProvider реализация
- Fallback на OpenAI
- Unit tests
- Базовая документация

**Should Have (P1):**
- Prompt caching
- Image compression
- Integration tests
- Полная документация

**Nice to Have (P2):**
- Response caching
- Grafana dashboard
- A/B тестирование
- Advanced monitoring

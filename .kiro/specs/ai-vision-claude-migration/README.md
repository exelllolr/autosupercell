# AI Vision Migration: OpenAI → Claude

## 🎯 Цель

Мигрировать AI Vision поиск товаров с OpenAI GPT-4o на Anthropic Claude 3.5 Sonnet для улучшения точности (85% → 92%) и снижения стоимости ($5 → $3 per 1K images).

## 📁 Структура спецификации

```
.kiro/specs/ai-vision-claude-migration/
├── README.md           # Этот файл (quick start)
├── requirements.md     # Требования и user stories
├── design.md          # Архитектура и технический дизайн
├── tasks.md           # Пошаговый план реализации
└── SPEC_SUMMARY.md    # Краткое резюме
```

## 🚀 Quick Start

### 1. Установить зависимости
```bash
pip install anthropic>=0.18.0 tenacity>=8.2.0
```

### 2. Получить API ключ
1. Зарегистрироваться: https://console.anthropic.com/
2. Создать API ключ: https://console.anthropic.com/settings/keys
3. Скопировать ключ (начинается с `sk-ant-api03-...`)

### 3. Настроить .env
```bash
# AI Provider Configuration
AI_PROVIDER=claude

# Anthropic API Key
ANTHROPIC_API_KEY=sk-ant-api03-ваш-ключ-здесь

# Optional
CLAUDE_MODEL=claude-3-5-sonnet-20241022
CLAUDE_MAX_TOKENS=1024
CLAUDE_TIMEOUT=30
```

### 4. Реализовать согласно tasks.md
```bash
# Следовать пошаговому плану
cat tasks.md
```

## 📊 Ожидаемые результаты

| Метрика | До (OpenAI) | После (Claude) | Улучшение |
|---------|-------------|----------------|-----------|
| Accuracy | 85% | 92%+ | +7% |
| Cost | $5/1K | $3/1K | -40% |
| Latency | 4s | 5s | +1s |
| Errors | 1.5% | <1% | -0.5% |

## ⏱️ Оценка

**Общее время:** 7.5 часов

| Фаза | Время |
|------|-------|
| Подготовка | 30 мин |
| ClaudeProvider | 2 часа |
| Интеграция | 1 час |
| Оптимизации | 1 час |
| Тестирование | 2 часа |
| Документация | 1 час |

## 📚 Документация

- **Setup Guide:** `docs/CLAUDE_SETUP.md`
- **Конфигурация:** `.claude`
- **Сравнение:** `AI_PROVIDERS_COMPARISON.md`

## 🔗 Ссылки

- [Anthropic Console](https://console.anthropic.com/)
- [API Docs](https://docs.anthropic.com/claude/reference/messages_post)
- [Vision Guide](https://docs.anthropic.com/claude/docs/vision)
- [Pricing](https://www.anthropic.com/pricing)

## ✅ Checklist

- [ ] Прочитать requirements.md
- [ ] Прочитать design.md
- [ ] Установить зависимости
- [ ] Получить API ключ
- [ ] Настроить .env
- [ ] Следовать tasks.md
- [ ] Запустить тесты
- [ ] Обновить документацию

## 💡 Ключевые решения

**Архитектура:**
```
Claude (primary) → OpenAI (fallback) → CSS selectors (last resort)
```

**Оптимизации:**
- Prompt Caching (50% экономии)
- Image Compression (resize + compress)
- Retry Logic (3 попытки)
- Fallback Chain (надёжность)

## 🎓 Методология

Спецификация создана согласно **SDD (Spec-Driven Development)** v5.0:
- Requirements-first подход
- Design перед кодом
- Пошаговый план
- Критерии приёмки

---

**Статус:** 📝 Specification Complete - Готово к реализации

**Следующий шаг:** Начать с `tasks.md` → Фаза 1: Подготовка

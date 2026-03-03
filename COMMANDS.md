# Команды AutoSupercell

## Готовность Docker к запуску

| Проверка | Статус |
|----------|--------|
| `docker compose config` | Ок — конфиг валиден |
| Файл `.env` | Нужен (скопировать из `.env.example`) |
| Файл `proxies.txt` | Нужен при включённых прокси (есть `proxies.txt.example`) |
| `prometheus.yml` | Ок — есть в корне |
| Папки `logs`, `screenshots`, `proofs`, `videos` | Создаются автоматически при первом запуске |

**Перед первым `docker compose up -d`:**
1. Создать `.env` из `.env.example` и при необходимости заполнить ключи.
2. При использовании прокси: подготовить `proxies.txt` (или пустой файл).

**Исправлено в проекте:**
- HEALTHCHECK в Dockerfile вызывает `/api/v1/health` (раньше был неверный `/health`).
- Prometheus скрапит метрики с `app:8000/metrics` (раньше был неверный порт 9090).

---

## Локальная разработка (без Docker)

### Окружение и установка

```powershell
# Создать venv (если ещё нет)
python -m venv venv

# Активировать venv (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Установить зависимости
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Установить браузер Playwright (для автоматизации)
playwright install chromium
playwright install-deps chromium
```

### Запуск приложения

```powershell
# API-сервер (порт 8000)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# или через Makefile (если установлен make)
make run-api
```

### Worker (очередь заказов)

```powershell
# Нужен запущенный Redis (localhost:6379)
arq app.workers.arq_worker.WorkerSettings

# или
python run_worker.py
# или
make run-worker
```

### Тесты

```powershell
# Запуск тестов (обязательно из venv)
.\venv\Scripts\python.exe -m pytest tests/ -v -o addopts=""

# С покрытием кода
.\venv\Scripts\python.exe -m pytest tests/ -v --cov=app --cov-report=term

# через Makefile
make test
```

---

## Если Supercell блокирует вход (unusual activity)

По умолчанию включены: длительная пауза на странице логина, медленный ввод email, прогрев supercell.com и постоянный профиль. Если блокировка остаётся, по очереди попробуй в `.env`:

1. **Patchright** — в проекте используется только Patchright (undetected Playwright). Если раньше ставили Playwright, убери конфликт и установи Chrome для Patchright:
   ```powershell
   pip uninstall playwright -y
   pip install -r requirements.txt
   patchright install chrome
   ```
   В `.env` для «рекомендуемого» режима (без наших доп. stealth): `BROWSER_USE_PATCHRIGHT=true`. Затем снова запустить тест.
2. **Отключить stealth-плагин**: `BROWSER_USE_STEALTH_PLUGIN=false`
3. **Отключить постоянный профиль**: `BROWSER_USE_PERSISTENT_PROFILE=false`
4. **Локально без прокси** (VPN на ПК): `PROXY_ENABLED=false`, затем `python examples/local_test.py`
5. **Резидентный прокси** (Novada): `PROXY_ENABLED=true`, `NOVADA_ENABLED=true`
6. **2Captcha** (платно): задать `CAPTCHA_2CAPTCHA_API_KEY=...`

---

## Ошибка net::ERR_CONNECTION_CLOSED при прокси

Если при запросе покупки/авторизации появляется **ERR_CONNECTION_CLOSED** и в ответе указан прокси (например `proxy_server: http://super.novada.pro:7777`):

1. **Проверить без прокси** — в `.env` поставить `PROXY_ENABLED=false`, перезапустить API и повторить запрос. Если без прокси всё работает, проблема в прокси.
2. **Novada** — проверить в `.env`: `NOVADA_ENABLED=true`, `NOVADA_USERNAME=...`, `NOVADA_API_KEY=...` (логин и API-ключ из личного кабинета Novada). Убедиться, что в `proxies.txt` не дублируется другой прокси, если используете только Novada.
3. **Файл proxies.txt** — при формате `user:pass@host:port` или `host:port:user:pass` проверить, что логин и пароль верные и прокси активен.

---

## Docker

### Подготовка перед первым запуском

1. **Файл `.env`** — скопировать из примера и заполнить:
   ```powershell
   copy .env.example .env
   # Отредактировать .env (ключи API, секреты и т.д.)
   ```

2. **Файл `proxies.txt`** (опционально) — если прокси включены в `.env`:
   ```powershell
   copy proxies.txt.example proxies.txt
   # Добавить свои прокси (по одному на строку)
   ```

3. **Папки** (создаются при первом запуске, но можно создать вручную):
   ```powershell
   mkdir logs, screenshots, proofs, videos
   ```

### Основные команды Docker

```powershell
# Собрать образы и запустить все сервисы в фоне
docker compose up -d

# Запустить с пересборкой образов
docker compose up -d --build

# Остановить все сервисы
docker compose down

# Остановить и удалить тома (redis-data, prometheus-data)
docker compose down -v

# Логи всех сервисов (в реальном времени)
docker compose logs -f

# Логи только приложения
docker compose logs -f app

# Логи только worker
docker compose logs -f worker

# Статус контейнеров
docker compose ps

# Перезапустить один сервис
docker compose restart app
docker compose restart worker
```

### Отдельные сервисы

```powershell
# Запустить только Redis
docker compose up -d redis

# Запустить приложение + Redis (без worker и Prometheus)
docker compose up -d redis app

# Собрать образ без кэша
docker compose build --no-cache
```

### Проверка после запуска

```powershell
# Health API
curl http://localhost:8000/api/v1/health

# Корень API
curl http://localhost:8000/

# Список маршрутов
curl http://localhost:8000/api/v1/routes

# Prometheus (метрики приложения на порту 8000)
curl http://localhost:8000/metrics

# Prometheus UI (скрапит метрики с app)
# Открыть в браузере: http://localhost:9091
```

### Деплой на Ubuntu (сервер)

Краткий чеклист для развёртывания на VPS Ubuntu с Docker. Полный гайд: [docs/DEPLOY_UBUNTU_DOCKER.md](docs/DEPLOY_UBUNTU_DOCKER.md).

```bash
# 1. Установка Docker (один раз)
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER
# Выйти из SSH и зайти снова

# 2. Клонирование и конфигурация
cd ~ && git clone <URL_РЕПО> autosupercell && cd autosupercell
cp .env.example .env && nano .env   # REDIS_HOST=redis, REDIS_PORT=6379, ключи API
touch proxies.txt
mkdir -p logs screenshots videos proofs

# 3. Запуск
docker compose up -d --build
docker compose ps && curl -s http://localhost:8000/api/v1/health
```

Для сборки на базе Ubuntu 22.04: `docker compose -f docker-compose.yml -f docker-compose.ubuntu.yml up -d --build`.

**Проверка после деплоя:** контейнеры `docker compose ps`, health `curl -s http://localhost:8000/api/v1/health`, логи `docker compose logs -f app`, при использовании Claude/Gemini/OpenAI — `curl -s http://localhost:8000/api/v1/ai/status`. Полный чеклист — раздел 3 в [docs/DEPLOY_UBUNTU_DOCKER.md](docs/DEPLOY_UBUNTU_DOCKER.md).

---

## Проверка автоматизации

После запуска Docker (или локального API) проверьте, что API и автоматизация доступны:

```powershell
# Из корня проекта (должен быть доступен API на http://localhost:8000)
python scripts/check_automation.py
```

Скрипт проверяет:
- доступность API (GET /, GET /api/v1/health);
- наличие маршрутов: health, orders/process, supercell/purchase;
- постановку заказа в очередь (Redis + worker);
- доступность /metrics.

**Полная проверка с браузером (Playwright) и покупкой в магазине:**

```powershell
python examples/purchase_demo.py
```

Будет запрошен email Supercell, код верификации (или пароль от почты для авто-кода), игра и название товара. Убедитесь, что в `.env` настроены AI-провайдер (OpenAI/Claude/Gemini) и при необходимости прокси.

**Быстрая проверка API без браузера (только очередь заказов):**

```powershell
python examples/test_api.py
```

Отправляет тестовый заказ в очередь; для обработки должен быть запущен worker.

---

## Прокси: почему не использовались

Браузерная автоматизация (покупка в магазине) использует прокси **только если** их видит **процесс API** (uvicorn или контейнер `app`). Проверьте:

1. **В `.env` должно быть:**
   ```env
   PROXY_ENABLED=true
   PROXY_LIST_FILE=proxies.txt
   ```
2. **Файл `proxies.txt`** в корне проекта (или путь из `PROXY_LIST_FILE`):
   - при **локальном** запуске API — файл в той же папке, откуда запускаете uvicorn;
   - при **Docker** — файл монтируется в контейнер (`./proxies.txt:/app/proxies.txt`), т.е. `proxies.txt` должен быть на хосте в папке с `docker-compose.yml`.
3. **Формат строк в `proxies.txt`:**  
   `host:port`, `user:pass@host:port` или `host:port:user:pass`. Строки, начинающиеся с `#`, пропускаются.

**Проверка статуса прокси до покупки:**

```powershell
curl http://localhost:8000/api/v1/proxy/status
```

В ответе: `proxy_enabled`, `proxies_loaded` (сколько загружено), `proxy_file_exists`. Если `proxies_loaded: 0` — включите `PROXY_ENABLED=true` и добавьте прокси в файл.

Скрипт `purchase_demo.py` перед отправкой запроса выводит статус прокси и в ответе покупки — поля `proxy_used` и `proxy_server`.

---

## Проверка AI-провайдера (Claude / OpenAI / Gemini)

В `.env` задаётся `AI_PROVIDER=openai` или `claude`, или `gemini`. Для Claude нужен `ANTHROPIC_API_KEY`.

Проверить, что выбранный провайдер доступен:

```powershell
curl http://localhost:8000/api/v1/ai/status
```

В ответе: `provider`, `available` (true/false), `message`. Если `available: false` — проверьте соответствующий ключ в `.env` (ANTHROPIC_API_KEY для Claude).

---

## Порты

| Сервис     | Порт  | Описание                    |
|-----------|-------|-----------------------------|
| app       | 8000  | FastAPI (API + /metrics)    |
| app       | 9090  | Зарезервирован (не используется в текущем коде) |
| redis     | 6379  | Redis                       |
| prometheus| 9091  | Prometheus UI (внутри контейнера 9090) |

---

## Makefile (кратко)

| Команда        | Действие                    |
|----------------|-----------------------------|
| `make help`    | Список команд               |
| `make install` | Установка зависимостей + Playwright |
| `make test`    | Запуск тестов               |
| `make run-api` | Запуск API (uvicorn)        |
| `make run-worker` | Запуск worker           |
| `make docker-up`   | Docker Compose up -d    |
| `make docker-down` | Docker Compose down     |
| `make docker-logs` | Логи Docker             |
| `make clean`   | Очистка кэша и артефактов   |

*На Windows для `make` нужен установленный Make (например через Chocolatey или WSL).*

План развёртывания autosupercell на VPS
1. Подготовка VPS
1.1 Создание виртуальной машины
Выбрать облако (Google Cloud Compute Engine, или другой провайдер: AWS, DigitalOcean, Timeweb и т.д.).
Создать VM: минимум 2 vCPU, 4 GB RAM (для браузера Playwright/Chromium в контейнере лучше не меньше).
ОС: Ubuntu 22.04 LTS (или Debian 12).
При необходимости: зарезервировать статический внешний IP для стабильного доступа и whitelist.
1.2 Сеть и файрвол
Открыть входящие порты:
22 — SSH;
8000 — API приложения (docker-compose.yml маппит 8000:8000);
при необходимости 9091 — Prometheus (только для внутреннего мониторинга, не обязательно наружу).
Исходящий трафик: без ограничений (для магазина Supercell, прокси, API ключей).
1.3 Доступ по SSH
Подключиться по SSH (ключ или пароль).
При желании: настроить SSH-ключ и отключить вход по паролю.
---

2. Подготовка окружения на сервере
2.1 Обновление системы и базовые пакеты
sudo apt update && sudo apt upgrade -y
Установить: curl, git, ca-certificates.
2.2 Установка Docker и Docker Compose
Установить Docker (официальный репозиторий для Ubuntu/Debian).
Установить Docker Compose (v2, плагин или standalone).
Добавить пользователя в группу docker: sudo usermod -aG docker $USER (и перелогиниться при необходимости).
Проверка: docker --version, docker compose version.
---

3. Размещение проекта на сервере
3.1 Получение кода
Клонировать репозиторий: git clone <repo_url> autosupercell && cd autosupercell.
Либо загрузить архив/скопировать файлы (scp, rsync).
3.2 Конфигурация приложения
Создать .env из примера: cp .env.example .env.
Заполнить в .env:
Обязательно: ENCRYPTION_KEY (32 байта), один из AI-ключей (OpenAI/Anthropic/Gemini), при необходимости ключи Plati/Kupikod/FunPay/Avito.
Сеть: для Docker оставить REDIS_HOST=redis, REDIS_PORT=6379 (имена сервисов из docker-compose.yml).
Браузер: для сервера обычно BROWSER_HEADLESS=true, BROWSER_USE_PERSISTENT_PROFILE=false или отдельный профиль; при необходимости прокси и 2Captcha.
Создать proxies.txt (формат из proxies.txt.example) или пустой файл, если прокси не используются.
3.3 Файлы и каталоги
Убедиться, что в корне проекта есть prometheus.yml (уже в репозитории).
Каталоги logs, screenshots, videos, proofs создаются при первом запуске контейнеров (COMMANDS.md); при необходимости создать вручную: mkdir -p logs screenshots videos proofs.
---

4. Запуск и деплой
4.1 Сборка и запуск
В корне проекта: docker compose config — проверить конфигурацию.
Сборка и запуск: docker compose up -d --build.
Проверить контейнеры: docker compose ps (должны быть в состоянии Up: app, redis, worker, prometheus).
4.2 Поведение при перезагрузке
В docker-compose.yml указано restart: unless-stopped — контейнеры поднимутся после перезагрузки сервера без дополнительных скриптов.
---

5. Проверка работы
5.1 Health и API
Локально на сервере: curl -s http://localhost:8000/api/v1/health.
Снаружи: http://<внешний_IP_VPS>:8000/api/v1/health.
При необходимости: проверить документацию API: http://<IP>:8000/docs.
5.2 Логи и ошибки
Логи всех сервисов: docker compose logs -f.
Только приложение: docker compose logs -f app.
Воркер: docker compose logs -f worker.
При ошибках: проверить .env, наличие proxies.txt, доступ к Redis (порт 6379 между контейнерами).
5.3 Мониторинг (опционально)
Prometheus: доступ к метрикам приложения через сервис app:8000/metrics (prometheus.yml); UI Prometheus — порт 9091 на хосте.
---

6. Дополнительно (по необходимости)
6.1 Безопасность
Сменить SSH-порт или ограничить вход по ключу.
Не открывать наружу порты Redis (6379) и Prometheus (9091), если не нужен внешний доступ.
Секреты хранить только в .env; не коммитить .env в репозиторий.
6.2 HTTPS и домен
Поставить перед приложением reverse proxy (Nginx/Caddy), выдать сертификат (Let's Encrypt).
Проксировать запросы на http://127.0.0.1:8000.
6.3 Обновление приложения
git pull (или загрузка новых файлов), затем docker compose up -d --build.
---

7. Внедрение Claude Vision на Ubuntu
Цель: включить на сервере AI-поиск по скриншотам через Claude (Vision), чтобы приложение использовало analyze_image для разбора страниц магазина.

7.1 Требования
Уже выполнено в рамках пунктов 1–4: Ubuntu, Docker, развёрнутое приложение, .env.
Исходящий HTTPS на api.anthropic.com (по умолчанию без ограничений).

7.2 Получение API-ключа Anthropic
Зарегистрироваться: https://platform.claude.com → Sign up / Log in.
Создать ключ: Settings → API Keys → Create Key; скопировать ключ (формат sk-ant-...).
Подробно: см. docs/ANTHROPIC_API_KEY_GUIDE.md.

7.3 Конфигурация на сервере
На сервере в каталоге проекта отредактировать .env:

# Включить провайдер Claude (в т.ч. Vision)
AI_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-ваш_ключ

Сохранить файл. Не коммитить .env в git.

7.4 Зависимости
В requirements.txt уже есть anthropic (используется в app/core/ai_providers/claude_provider.py). При сборке образа (docker compose up -d --build) пакет ставится в контейнер — отдельная установка на хосте не нужна.

7.5 Модель Vision в коде
В claude_provider.py используется модель с Vision: claude-3-5-sonnet-20241022. Менять ничего не обязательно; при желании обновить на актуальную модель в документации Anthropic (docs.anthropic.com).

7.6 Перезапуск и проверка
Перезапустить контейнеры, чтобы подхватить .env:
docker compose up -d --build

Проверить доступность провайдера:
curl -s http://localhost:8000/api/v1/ai/status

Ожидаемый ответ при корректном ключе:
{"provider":"claude","available":true,"message":"Провайдер claude доступен."}

Если "available": false — проверить ANTHROPIC_API_KEY в .env и что ключ активен в Console; логи: docker compose logs -f app.

7.7 Где используется Vision
Метод analyze_image вызывается из AIProductSearch (app/core/ai_product_search.py) при поиске товаров по скриншоту страницы магазина. После включения Claude и корректного ключа сценарии, использующие AI-поиск, будут использовать Claude Vision на сервере Ubuntu без дополнительных шагов.
---
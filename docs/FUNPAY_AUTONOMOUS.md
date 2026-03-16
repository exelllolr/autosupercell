# Интеграция FunPay и автономный скрипт покупки

## Обзор

- Заказы FunPay попадают в очередь Redis `funpay:orders:pending` (через API или бота).
- Скрипт `examples/funpay_purchase_auto.py` забирает заказы из очереди, вызывает покупку в Supercell Store и обновляет статус в FunPay.
- При блокировке Supercell (unusual activity, Something went wrong и т.д.) скрипт повторяет попытку до успеха или до лимита (50 раз).

---

## Локальная проверка (перед выкладкой на сервер)

Проверьте цепочку «очередь → скрипт → API → покупка» у себя на машине, затем переносите на сервер.

### Шаг 1: Запустить Redis

**Вариант A — Docker (если есть):**

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

**Вариант B — установленный Redis:**

```bash
# Windows (если установлен): redis-server
# Linux/macOS: sudo systemctl start redis   или  redis-server
```

Проверка: `redis-cli ping` → ответ `PONG`.

### Шаг 2: Запустить API

В **первом терминале** из корня проекта:

```bash
cd c:\Users\exelllolr\Desktop\autosupercell
# Активируйте venv, если используете:
# .venv\Scripts\activate   (Windows)   или   source .venv/bin/activate   (Linux/macOS)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Или: `make run-api` (если Makefile есть).

Проверка: откройте в браузере http://127.0.0.1:8000/api/v1/health — должен быть `{"status":"healthy",...}`.

### Шаг 3: Настроить .env

В корне проекта в `.env` должны быть минимум:

- `REDIS_HOST=localhost`, `REDIS_PORT=6379`
- `AUTOSUPERCELL_API_URL=http://127.0.0.1:8000/api/v1`
- Если в API задан `API_SECRET_KEY` — задайте тот же ключ в `AUTOSUPERCELL_API_KEY`

Для реальной покупки дальше понадобятся прокси, Google Pay, Supercell и т.д. — как в основном проекте.

### Шаг 4: Добавить тестовый заказ в очередь

Во **втором терминале** (или Postman/curl с другой машины):

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/orders/funpay" ^
  -H "Content-Type: application/json" ^
  -d "{\"order_id\":\"test-local-1\",\"email\":\"ВАШ_EMAIL_ДЛЯ_ТЕСТА\",\"game\":\"brawl-stars\",\"product_name\":\"80 Gems\"}"
```

На Linux/macOS (без `^`, одна строка):

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/orders/funpay" \
  -H "Content-Type: application/json" \
  -d '{"order_id":"test-local-1","email":"ВАШ_EMAIL","game":"brawl-stars","product_name":"80 Gems"}'
```

В **PowerShell** (Windows):

```powershell
$body = '{"order_id":"test-local-1","email":"ВАШ_EMAIL","game":"brawl-stars","product_name":"80 Gems"}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/orders/funpay" -Method Post -Body $body -ContentType "application/json"
```

Если на API включён ключ, добавьте заголовок: `-H "X-API-Key: ВАШ_КЛЮЧ"` (в PowerShell: `-Headers @{"X-API-Key"="ВАШ_КЛЮЧ"}`).

Успех: ответ `{"success":true,"order_id":"test-local-1",...}`.

### Шаг 5: Запустить скрипт обработки заказов

В **третьем терминале** из корня проекта:

```bash
cd c:\Users\exelllolr\Desktop\autosupercell
python examples/funpay_purchase_auto.py
```

Ожидаемое поведение:

- В консоли появится что-то вроде: `[Заказ test-local-1] email=... game=brawl-stars product=80 Gems`, затем «Попытка 1/50...».
- Скрипт вызовет API покупки; дальше всё зависит от настроек (Supercell, прокси, код верификации и т.д.). Главное — убедиться, что заказ **забрался из очереди** и запрос на покупку **уходит**.

Остановка скрипта: **Ctrl+C**.

### Шаг 6: Что проверили локально

- Redis доступен, API отвечает.
- POST `/orders/funpay` кладёт заказ в очередь.
- Скрипт забирает заказ из очереди и дергает `/supercell/purchase`.

После этого можно выкладывать на сервер.

---

## Выкладка на сервер

1. Скопируйте проект на сервер (git clone или архив).
2. На сервере: установите зависимости, настройте `.env` (Redis, API URL, ключи, прокси, Google и т.д.).
3. Запустите Redis и API так же, как локально (или через Docker/docker-compose).
4. Запустите скрипт постоянно:
   - **nohup**: `nohup python examples/funpay_purchase_auto.py >> logs/funpay_auto.log 2>&1 &`
   - или **systemd** — см. раздел «Запуск на сервере» ниже (unit-файл и `systemctl enable/start`).

На сервере `AUTOSUPERCELL_API_URL` укажите на ваш API (например `http://127.0.0.1:8000/api/v1`, если API на том же сервере).

---

## Как наполнить очередь

### Вариант 1: POST /api/v1/orders/funpay

Отправьте JSON с заказом (сырые данные чата или уже распарсенные поля):

**Сырые данные (парсер извлечёт email, OTP, игру, товар):**

```json
{
  "order_id": "12345",
  "offer_title": "Brawl Stars 80 Gems",
  "description": "Описание лота",
  "messages": [
    {"author": "buyer", "text": "email: user@gmail.com"},
    {"author": "buyer", "text": "код: 123456"}
  ]
}
```

**Уже распарсенные данные:**

```json
{
  "order_id": "12345",
  "email": "user@gmail.com",
  "game": "brawl-stars",
  "product_name": "80 Gems",
  "verification_code": "123456"
}
```

Пример с curl (с API-ключом):

```bash
curl -X POST "http://localhost:8000/api/v1/orders/funpay" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY" \
  -d '{"order_id":"12345","email":"user@gmail.com","game":"brawl-stars","product_name":"80 Gems"}'
```

### Вариант 2: Бот на FunPayAPI

Настройте бота на [FunPayAPI](https://pypi.org/project/FunPayAPI/): при событии `NEW_ORDER` / новых сообщениях в чате отправляйте данные на ваш сервер `POST /api/v1/orders/funpay` (тело как выше).

## Запуск автономного скрипта

1. Убедитесь, что запущены API и Redis.
2. В `.env` заданы:
   - `REDIS_HOST`, `REDIS_PORT` (и при необходимости `REDIS_PASSWORD`, `REDIS_DB`)
   - `AUTOSUPERCELL_API_URL` (по умолчанию `http://localhost:8000/api/v1`)
   - `AUTOSUPERCELL_API_KEY` — если на сервере включён `API_SECRET_KEY`
3. Запуск:

```bash
python examples/funpay_purchase_auto.py
```

Скрипт работает бесконечно: при пустой очереди ждёт 60 секунд и снова проверяет. Для остановки — Ctrl+C.

---

## Запуск на сервере (постоянно смотреть заказы и выполнять их)

Чтобы скрипт на сервере постоянно просматривал очередь и обрабатывал заказы, сделайте следующее.

### 1. Что должно быть запущено

- **Redis** — очередь `funpay:orders:pending` (те же хост/порт, что и для основного API).
- **API приложения** (uvicorn) — скрипт дергает `POST /supercell/purchase` и `PUT /orders/funpay/{id}/status` на этом API.

Пример запуска API (если ещё не запущен):

```bash
cd /path/to/autosupercell
source .venv/bin/activate   # или: python -m venv .venv && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. Переменные окружения

В корне проекта создайте/отредактируйте `.env` (скрипт сам подхватит его при запуске из этой папки):

```env
REDIS_HOST=localhost
REDIS_PORT=6379
# REDIS_PASSWORD=...
# REDIS_DB=0

AUTOSUPERCELL_API_URL=http://127.0.0.1:8000/api/v1
AUTOSUPERCELL_API_KEY=ваш_ключ_из_API_SECRET_KEY
```

Если API и скрипт на одном сервере, `AUTOSUPERCELL_API_URL` можно оставить `http://127.0.0.1:8000/api/v1`.

### 3. Запуск скрипта в фоне (nohup)

Из корня проекта:

```bash
cd /path/to/autosupercell
source .venv/bin/activate
nohup python examples/funpay_purchase_auto.py >> logs/funpay_auto.log 2>&1 &
echo $!   # сохраните PID, чтобы потом убить: kill <PID>
```

Логи будут в `logs/funpay_auto.log`. Папку `logs/` создайте, если её нет: `mkdir -p logs`.

### 4. Запуск как сервис systemd (рекомендуется)

Создайте файл `/etc/systemd/system/funpay-auto.service`. **Не используйте `EnvironmentFile=`**, если путь к файлу может не существовать — иначе сервис не стартует с ошибкой «Failed to load environment files». Скрипт сам подхватывает `.env` из рабочей директории.

Подставьте **реальный** путь к проекту (например `/root/autosupercell` или `/home/user/autosupercell`) и имя пользователя. Путь к Python — каталог `venv` или `.venv` в проекте:

```ini
[Unit]
Description=FunPay Auto Purchase
After=network.target redis.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/autosupercell
Environment=PATH=/root/autosupercell/venv/bin:/usr/bin
ExecStart=/root/autosupercell/venv/bin/python examples/funpay_purchase_auto.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Готовый пример можно скопировать из репозитория: `docs/funpay-auto.service.example`.

Включите и запустите:

```bash
sudo systemctl daemon-reload
sudo systemctl enable funpay-auto
sudo systemctl start funpay-auto
sudo systemctl status funpay-auto
```

Просмотр логов:

```bash
journalctl -u funpay-auto -f
```

#### Если сервис не стартует (Failed to load environment files / No such file or directory)

- **«Failed to load environment files: No such file or directory»** — в unit указан `EnvironmentFile=/какой-то/путь/.env`, а такого файла или каталога нет. Либо удалите строку `EnvironmentFile=`, либо сделайте её опциональной: `EnvironmentFile=-/реальный/путь/к/проекту/.env` (минус перед путём = не падать, если файла нет).
- **«Failed to run 'start' task: No such file or directory»** — неверный путь в `ExecStart` или `WorkingDirectory`. Проверьте:
  - `WorkingDirectory` — существующая папка проекта (например `ls /root/autosupercell`).
  - В `ExecStart` путь к `python` — существующий файл (например `ls /root/autosupercell/venv/bin/python`). Если venv называется `.venv`, подставьте `.venv` вместо `venv`.

После правок: `sudo systemctl daemon-reload` и снова `sudo systemctl start funpay-auto`.

### 5. Откуда берутся заказы

- Вручную: `curl -X POST "http://ВАШ_СЕРВЕР:8000/api/v1/orders/funpay" -H "Content-Type: application/json" -H "X-API-Key: KEY" -d '{"order_id":"123","email":"...","game":"brawl-stars","product_name":"80 Gems"}'`
- Бот FunPayAPI на том же или другом сервере при новом заказе/сообщениях в чате отправляет POST на ваш `http://СЕРВЕР:8000/api/v1/orders/funpay` с телом заказа — скрипт подхватит заказ из очереди и выполнит покупку.

## Переменные FunPay в .env

- **FUNPAY_GOLDEN_KEY** — это ваш **golden key** из настроек FunPay (профиль на funpay.com → настройки → токен для ботов). Его использует **бот на FunPayAPI**: бот подключается к FunPay по этому ключу, получает новые заказы и сообщения в чате и отправляет их в наш API (POST /orders/funpay). В `.env` основного проекта укажите:
  ```env
  FUNPAY_GOLDEN_KEY=zqmcmol9xdj12ko0geewx707o2kqowdt
  ```
  (подставьте свой ключ; сам наш API этот ключ не дергает — он нужен скрипту/боту, который будет слать заказы в очередь.)

- **FUNPAY_API_URL** — у FunPay **нет официального REST API**. Этого URL нет «где взять»: его не выдаёт FunPay. В нашем коде `FUNPAY_API_URL` используется только если вы подняли **свой прокси-сервис**, который:
  - по запросу отдаёт заказ с чатом (GET …/orders/{id}/chat),
  - принимает обновление статуса (PATCH …/orders/{id}).
  Если такого прокси нет — **оставьте пустым**:
  ```env
  FUNPAY_API_URL=
  ```
  Обработка заказов и покупка от этого не пострадают (заказы приходят в очередь через POST /orders/funpay). Не будет работать только автоматическая отправка статуса «выполнено/ошибка» обратно в FunPay через наш сервер; бот может обновлять статус сам через FunPayAPI после получения ответа от нас.

- **FUNPAY_API_KEY** — нужен только если вы используете свой прокси (см. выше); иначе оставьте пустым.

## Обновление статуса в FunPay

После успеха или ошибки покупки скрипт вызывает `PUT /api/v1/orders/funpay/{order_id}/status` с телом `{"status": "completed"|"failed", "proof_data": {...}}`. Сервер передаёт обновление в `funpay_integration.update_order_status()`. Для работы обновления должен быть настроен `FUNPAY_API_URL` и `FUNPAY_API_KEY` (ваш прокси/сервис, который умеет обновлять заказы в FunPay).

## Резервные коды Google

Для длительной автономной работы с Google Pay настройте до 10 резервных кодов в `.env`:

```env
GOOGLE_BACKUP_CODES=55192680,12345678,87654321,...
```

Индекс следующего кода хранится в `data/.google_backup_code_next_index`. После исчерпания кодов — сгенерируйте новые в Google Account → Security → 2-Step Verification → Backup codes и обнулите файл состояния (удалите файл или запишите в него `0`).

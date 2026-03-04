# Деплой autosupercell на Ubuntu с Docker

Пошаговый гайд по развёртыванию на сервере Ubuntu (22.04 LTS рекомендуется) с Docker и Docker Compose.

---

## 1. Файлы и каталоги для переноса

### 1.1 Рекомендуемый способ — клонирование репозитория

На сервере клонируйте репозиторий (SSH или HTTPS). В репозиторий не входят (создаются на сервере вручную):

- **`.env`** — скопировать из `.env.example` и заполнить (ключи, Redis и т.д.).
- **`proxies.txt`** — создать из `proxies.txt.example` или пустой файл.

Каталоги **`logs/`**, **`screenshots/`**, **`videos/`**, **`proofs/`** монтируются в контейнеры; при первом запуске их можно создать вручную или позволить Docker создать при монтировании.

### 1.2 Перенос архивом (без git)

Если код переносите не через git, упакуйте на локальной машине минимум:

| Категория      | Что включить |
|----------------|--------------|
| Корень проекта | `app/`, `requirements.txt`, `Dockerfile`, `Dockerfile.ubuntu`, `docker-compose.yml`, `prometheus.yml`, `.env.example`, `proxies.txt.example`, `COMMANDS.md` |
| Документация   | `docs/` (по желанию) |
| Примеры        | `examples/` (по желанию) |

На сервере после распаковки: создать `.env` из `.env.example`, создать `proxies.txt`.

---

## 2. Команды для настройки на сервере Ubuntu

### 2.1 Обновление системы и базовые пакеты

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git ca-certificates
```

### 2.2 Установка Docker и Docker Compose

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

**Важно:** после `usermod -aG docker $USER` выйдите из SSH и зайдите снова (или выполните `newgrp docker`).

Запуск и автозапуск демона Docker (если при `docker compose up` появляется *Cannot connect to the Docker daemon*):

```bash
sudo systemctl start docker
sudo systemctl enable docker
sudo systemctl status docker   # убедиться, что active (running)
```

Проверка клиента:

```bash
docker --version
docker compose version   # или: docker-compose --version
```

**Если выдаёт `unknown command: docker compose`** — на сервере нет плагина Compose v2. Используйте старый клиент с дефисом:

```bash
# Установка docker-compose (standalone), если ещё нет
sudo apt install -y docker-compose
# Дальше везде используйте docker-compose вместо docker compose:
docker-compose build --no-cache app
docker-compose up -d --build
docker-compose ps
```

### 2.3 Размещение проекта

**Вариант A — клонирование по SSH:**

```bash
cd ~
git clone git@github.com:<org>/<repo>.git autosupercell
cd autosupercell
```

**Вариант B — клонирование по HTTPS:**

```bash
cd ~
git clone https://github.com/<org>/<repo>.git autosupercell
cd autosupercell
```

**Вариант C — загрузка архива:**

```bash
cd ~
# После копирования архива на сервер (scp/rsync):
tar -xzf autosupercell.tar.gz && cd autosupercell
```

**Если `git clone` падает с `GnuTLS recv error`, `HTTP/2 stream was not closed cleanly` или `early EOF`** (нестабильная сеть, ограничения провайдера):

Отключить HTTP/2 для Git (часто решает обрывы) и увеличить буфер:

```bash
git config --global http.version HTTP/1.1
git config --global http.postBuffer 524288000
rm -rf autosupercell
git clone --depth 1 https://github.com/exelllolr/autosupercell.git autosupercell
cd autosupercell
```

Либо только буфер без смены протокола:

```bash
git config --global http.postBuffer 524288000
git clone --depth 1 https://github.com/exelllolr/autosupercell.git autosupercell
cd autosupercell
```

### 2.4 Конфигурация приложения

```bash
cp .env.example .env
nano .env   # или vim — заполнить переменные
```

В `.env` для Docker обязательно:

- `REDIS_HOST=redis`
- `REDIS_PORT=6379`

Остальное — по `.env.example` (AI-ключи, прокси, платёжные ключи, `ENCRYPTION_KEY` и т.д.).

```bash
touch proxies.txt
# Либо: cp proxies.txt.example proxies.txt
```

```bash
mkdir -p logs screenshots videos proofs
```

### 2.5 Сборка и запуск

```bash
docker compose config          # проверка конфигурации
docker compose up -d --build   # сборка образов и запуск в фоне
```

Для сборки на базе образа Ubuntu 22.04 используйте дополнительный compose-файл:

```bash
docker compose -f docker-compose.yml -f docker-compose.ubuntu.yml up -d --build
```

**Если сборка падает с `failed to fetch metadata: exit status 2`** — ошибка на шаге apt или pip внутри образа. Узнать точный шаг:

```bash
docker compose build --no-cache app 2>&1
```

Смотреть конец вывода: какой `RUN` упал (apt-get, pip install или playwright install). Частые причины: нет доступа к репозиториям (проверить сеть/DNS), блокировка PyPI или Docker Hub. Попробовать образ на Ubuntu: `docker compose -f docker-compose.yml -f docker-compose.ubuntu.yml up -d --build`.

### 2.6 Файрвол (при необходимости)

```bash
sudo ufw allow 22
sudo ufw allow 8000
sudo ufw enable
```

Порт 9091 (Prometheus) наружу лучше не открывать.

---

## 3. Проверка после деплоя (чеклист)

1. **Контейнеры запущены:**

   ```bash
   docker compose ps
   ```

   Ожидаются в состоянии `Up`: `autosupercell-app`, `autosupercell-redis`, `autosupercell-worker`, `autosupercell-prometheus`.

2. **Health API:**

   Локально на сервере:

   ```bash
   curl -s http://localhost:8000/api/v1/health
   ```

   Снаружи: `http://<IP_СЕРВЕРА>:8000/api/v1/health`.

3. **Документация API:**  
   `http://<IP>:8000/docs`

4. **Логи приложения:**

   ```bash
   docker compose logs -f app
   ```

   Все сервисы: `docker compose logs -f`.

5. **AI-провайдер (если используется Claude/Gemini/OpenAI):**

   ```bash
   curl -s http://localhost:8000/api/v1/ai/status
   ```

   При корректном ключе ожидается что-то вроде: `{"provider":"claude","available":true,...}`.

При ошибках: проверить `.env`, наличие `proxies.txt`, доступ к Redis между контейнерами (порт 6379).

---

## 3.1 Запуск демо (supercell_full_auth_demo.py)

Скрипт дергает API (полная авторизация Supercell + Google или только логин Supercell). Варианты:

**На сервере (в контейнере app, интерактивно):**

```bash
docker-compose exec -it autosupercell-app python /app/examples/supercell_full_auth_demo.py
```

Дальше скрипт запросит email Supercell, код из письма, при полной авторизации — Google email/пароль. API уже на localhost внутри контейнера.

**На сервере (на хосте, если установлен Python и requests):**

```bash
cd ~/autosupercell
python3 examples/supercell_full_auth_demo.py
```

**С вашего ПК (API на VPS):**

Укажите URL API через переменную окружения и запустите скрипт локально (нужен Python и `pip install requests`):

```bash
set AUTOSUPERCELL_API_URL=http://130.12.44.191:8000/api/v1
python examples\supercell_full_auth_demo.py
```

На Linux/macOS: `export AUTOSUPERCELL_API_URL=http://130.12.44.191:8000/api/v1` затем `python3 examples/supercell_full_auth_demo.py`.

Скриншоты сохраняются в `screenshots/` внутри контейнера; с хоста: `docker-compose exec autosupercell-app ls -la /app/screenshots`.

---

## 4. Опции: образ на базе Ubuntu

По умолчанию используется [Dockerfile](../Dockerfile) (Debian Bookworm). Чтобы собирать образ на базе Ubuntu 22.04 ([Dockerfile.ubuntu](../Dockerfile.ubuntu)), используйте второй compose-файл:

```bash
docker compose -f docker-compose.yml -f docker-compose.ubuntu.yml up -d --build
```

Файл [docker-compose.ubuntu.yml](../docker-compose.ubuntu.yml) переопределяет только сборку сервисов `app` и `worker`.

---

## 5. Краткая шпаргалка команд

```bash
# Установка Docker (один раз)
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER

# Проект и запуск
cd ~/autosupercell
cp .env.example .env && nano .env
touch proxies.txt
mkdir -p logs screenshots videos proofs
docker compose up -d --build

# Проверка
docker compose ps && curl -s http://localhost:8000/api/v1/health

# Логи
docker compose logs -f
```

---

## 6. Белые скриншоты и ERR_NAME_NOT_RESOLVED

Если в ответе API приходит ошибка **`Page.goto: net::ERR_NAME_NOT_RESOLVED at https://store.supercell.com/`**, браузер внутри контейнера не может разрешить домен (DNS). Страница не загружается, поэтому скриншот получается **белым**.

**Что сделать:**

1. **DNS в контейнерах** — в [docker-compose.yml](../docker-compose.yml) для `app` и `worker` заданы: `127.0.0.11` (встроенный DNS Docker — резолв имён `redis`/`app`), затем `8.8.8.8` и `1.1.1.1`. Не монтировать в контейнер `/etc/resolv.conf` с хоста — иначе не резолвится `redis` и воркер падает с «Temporary failure in name resolution». После правок: `docker-compose up -d --build`.

2. **Проверить разрешение имён из контейнера:**
   ```bash
   docker-compose exec autosupercell-app nslookup store.supercell.com
   ```
   Если команда не находит адрес — проблема в сети/DNS хоста или в доступе контейнера к интернету.

3. **Использовать прокси** — если хостинг или регион блокирует Supercell, включите прокси в `.env`: `PROXY_ENABLED=true`, добавьте рабочие прокси в `proxies.txt` и перезапустите контейнеры.

4. **Глобальный DNS для Docker (Ubuntu):** если контейнеры всё равно не резолвят внешние домены, задайте DNS на уровне демона:
   ```bash
   sudo bash -c 'cat > /etc/docker/daemon.json << EOF
   {
     "dns": ["8.8.8.8", "8.8.4.4"]
   }
   EOF'
   sudo systemctl restart docker
   docker-compose down && docker-compose up -d
   ```
   Затем проверьте: `docker exec autosupercell-app cat /etc/resolv.conf` и `docker exec autosupercell-app nslookup store.supercell.com`.

5. **Логи:** `docker-compose logs -f app` — смотреть полный текст ошибки и стек.

---

## См. также

- [docs/plan.md](plan.md) — общий план развёртывания на VPS, переменные окружения, Claude Vision.
- [COMMANDS.md](../COMMANDS.md) — команды Docker и локальной разработки.

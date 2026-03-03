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

Проверка:

```bash
docker --version
docker compose version
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

## См. также

- [docs/plan.md](plan.md) — общий план развёртывания на VPS, переменные окружения, Claude Vision.
- [COMMANDS.md](../COMMANDS.md) — команды Docker и локальной разработки.

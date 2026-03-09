# Чеклист на сервере Ubuntu — что сделать по порядку

Подключаешься по SSH (`ssh root@IP_СЕРВЕРА` или `ssh user@IP`) и выполняешь команды **по шагам**. После каждого блока проверь вывод — если ошибка, не переходи к следующему шагу.

---

## Шаг 1. Docker установлен и запущен

```bash
docker --version
sudo systemctl start docker
sudo systemctl enable docker
sudo systemctl status docker
```

В последней команде должно быть **active (running)**. Если `docker compose` не найден — установи: `sudo apt install -y docker-compose`. Дальше везде используй **docker-compose** (с дефисом).

---

## Шаг 2. Проект на сервере

```bash
cd ~
# Если клон по HTTPS падает (GnuTLS/HTTP2 error) — сначала:
git config --global http.version HTTP/1.1
git config --global http.postBuffer 524288000

git clone --depth 1 https://github.com/exelllolr/autosupercell.git autosupercell
cd autosupercell
```

Если клонировал раньше — просто: `cd ~/autosupercell && git pull`.

---

## Шаг 3. Конфиг и файлы для контейнеров

```bash
cp .env.example .env
nano .env
```

В `.env` обязательно выставить:
- `REDIS_HOST=redis`
- `REDIS_PORT=6379`
- Остальное по необходимости (AI-ключи, `ENCRYPTION_KEY` и т.д.). Сохранить и выйти (Ctrl+O, Enter, Ctrl+X).

```bash
touch proxies.txt
mkdir -p logs screenshots videos proofs
```

---

## Шаг 4. (По желанию) Глобальный DNS для Docker

Если потом будет **ERR_NAME_NOT_RESOLVED** при открытии store.supercell.com, выполни один раз:

```bash
sudo bash -c 'cat > /etc/docker/daemon.json << EOF
{
  "dns": ["8.8.8.8", "8.8.4.4"]
}
EOF'
sudo systemctl restart docker
```

---

## Шаг 5. Сборка и запуск

```bash
cd ~/autosupercell
docker-compose down
docker-compose up -d --build
```

Подожди **15–20 секунд** (приложение поднимается не сразу).

---

## Шаг 6. Проверка

```bash
docker-compose ps
curl -s http://localhost:8000/api/v1/health
```

Ожидаемо:
- В `ps` все контейнеры в состоянии **Up** (app — healthy, worker может быть health: starting).
- В ответе `curl`: `{"status":"healthy","service":"autosupercell"}`.

Проверка DNS из контейнера (если раньше были ошибки с store.supercell.com):

```bash
docker-compose exec autosupercell-app nslookup store.supercell.com
```

Должен вернуться адрес (например 18.238.217.62). Если «can't resolve» — см. раздел 6 в [DEPLOY_UBUNTU_DOCKER.md](DEPLOY_UBUNTU_DOCKER.md) (прокси или daemon.json).

---

## Шаг 7. Запуск демо (покупка / авторизация)

С хоста (в каталоге проекта):

```bash
cd ~/autosupercell
python3 examples/purchase_demo.py
```

Либо из контейнера (если на хосте нет venv/зависимостей):

```bash
docker-compose exec -it autosupercell-app python /app/examples/purchase_demo.py
```

Скриншоты появятся в `~/autosupercell/screenshots/`, логи: `docker-compose logs -f app`.

---

## Если не записывается видео на сервере

1. **В `.env` должно быть:**
   ```env
   BROWSER_RECORD_VIDEO=true
   BROWSER_USE_PERSISTENT_PROFILE=false
   ```
   Запись видео в коде включена только при обычном контексте (не persistent). На сервере в headless и так используется обычный контекст, но явно выставить `BROWSER_USE_PERSISTENT_PROFILE=false` стоит.

2. **Каталог и том:** в `docker-compose` задано `./videos:/app/videos`. На хосте:
   ```bash
   ls -la ~/autosupercell/videos
   ```
   Каталог должен существовать и быть доступен для записи (если создаётся от root — права обычно ок).

3. **Видео появляется после закрытия контекста** — файл дописывается при корректном закрытии браузера. Если процесс упал по таймауту или ошибке до вызова `close()`, файл может не появиться или быть пустым. В логах при успешном закрытии будет: `Видео сессии сохранено: /app/videos/....webm`.

4. **Перезапуск после смены .env:** `docker-compose restart app` (или `up -d --build` после правок).

---

## Краткая шпаргалка (всё уже настроено)

```bash
cd ~/autosupercell
docker-compose ps
curl -s http://localhost:8000/api/v1/health
docker-compose logs -f app
docker-compose down && docker-compose up -d --build
```

Полный гайд: [DEPLOY_UBUNTU_DOCKER.md](DEPLOY_UBUNTU_DOCKER.md).

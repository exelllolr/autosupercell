# Настройка сервера: X11, SSH-ключ, клонирование репо, Docker

Пошаговая инструкция для голого Linux-сервера (Ubuntu/Debian).

---

## 1. Установка X11 на сервере и проверка проброса дисплея

### 1.1 Установка X11 и минимального окружения

На сервере (по SSH):

```bash
# Обновление пакетов
sudo apt update && sudo apt upgrade -y

# X11 сервер и базовые утилиты
sudo apt install -y xorg x11-xserver-utils x11-utils

# Небольшая программа с окном (для теста — часы xclock и другие)
sudo apt install -y x11-apps
```

### 1.2 Запуск тестовых программ (проверка X11)

В пакете `x11-apps` есть несколько программ с окнами — любую можно использовать для проверки проброса:

| Команда   | Что показывает |
|-----------|-----------------|
| `xclock`  | Часы (аналоговые) |
| `xeyes`   | Два глаза, следящие за курсором |
| `xcalc`   | Калькулятор |
| `xterm`   | Текстовый терминал в окне |
| `xload`   | График загрузки системы |
| `xlogo`   | Логотип X |

После подключения по SSH с `-Y` (например `ssh -Y root@130.12.44.191`) запусти на сервере любую команду — окно должно появиться на твоём ноутбуке. Если нет — см. раздел 4 (настройка X11 на ноуте).

### 1.3 Просмотр окна браузера с сервера на ноуте

Тот же принцип: подключаешься по SSH с пробросом X11 — любое окно (в том числе браузера) рисуется у тебя на ноутбуке.

**Вариант A — обычный браузер (Firefox/Chromium) для проверки:**

На сервере (уже по `ssh -Y root@...`):

```bash
# Установка одного из браузеров (достаточно одного)
sudo apt install -y firefox-esr
# или
sudo apt install -y chromium-browser
```

Запуск (на сервере):

```bash
firefox
# или
chromium
```

Окно браузера откроется на твоём ноуте. Может тормозить из‑за передачи картинки по сети — это нормально.

**Вариант B — браузер из приложения (SuperCell / autosupercell):**

Приложение запускает Chrome через Playwright/Patchright. Чтобы **видеть** этот браузер на ноуте:

1. Подключайся к серверу с пробросом X11: `ssh -Y root@130.12.44.191`.
2. На сервере в проекте выставь в `.env`: `BROWSER_HEADLESS=false`.
3. Запусти приложение (Docker или напрямую Python). Chromium откроется в режиме с окном и будет рисоваться в твой `DISPLAY` — то есть на ноуте.

Пример (на сервере, в каталоге проекта):

```bash
export BROWSER_HEADLESS=false
# затем запуск приложения, например:
docker compose up
# или
uvicorn app.main:app --host 0.0.0.0
```

Окно браузера, которое открывает приложение (логин, магазин и т.д.), будет отображаться на твоём ноутбуке, пока открыта эта SSH-сессия с `-Y`.

---

## 2. Удаление программы часов с сервера

После проверки проброса X11 программу часов можно не ставить/удалить:

```bash
# Удалить только пакет с приложениями (часы и др.)
sudo apt remove -y x11-apps

# Опционально: удалить зависимости, которые больше не нужны
sudo apt autoremove -y
```

Сервер X11 (`xorg`) можно оставить, если планируешь запускать другие GUI-приложения с пробросом на ноут.

---

## 3. SSH-ключ, GitHub, клонирование репо, Docker

### 3.1 Генерация SSH-ключа на сервере

На сервере:

```bash
# Генерация ключа (email — свой или любой)
ssh-keygen -t ed25519 -C "server@github" -f ~/.ssh/id_ed25519_github -N ""
```

Просмотр **публичного** ключа (его нужно вставить в GitHub):

```bash
cat ~/.ssh/id_ed25519_github.pub
```

Скопируй вывод (одна строка вида `ssh-ed25519 AAAA... server@github`).

### 3.2 Добавление ключа в GitHub

1. Открой: https://github.com/egorz-code/SuperCell/settings/keys/new  
2. **Title:** например `Server` или `VPS`  
3. **Key:** вставь содержимое `~/.ssh/id_ed25519_github.pub`  
4. Сохрани (Add SSH key).

### 3.3 Настройка SSH для использования этого ключа к GitHub

На сервере:

```bash
# Конфиг SSH для GitHub
cat >> ~/.ssh/config << 'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_github
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

Проверка:

```bash
ssh -T git@github.com
```

Ожидается сообщение вроде: `Hi egorz-code/SuperCell! You've successfully authenticated...`

### 3.4 Клонирование репозитория на сервере

```bash
cd ~
git clone git@github.com:egorz-code/SuperCell.git
cd SuperCell
```

Если репо приватное — доступ будет по ключу, который ты добавил.

### 3.5 Запуск Docker

Убедись, что Docker установлен:

```bash
# Установка Docker (если ещё не установлен)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Выйти из SSH и зайти снова, чтобы группа docker применилась
```

Поднятие контейнеров (из корня репо, где есть `docker-compose.yml`):

```bash
cd ~/SuperCell
docker compose up -d
# или старая версия:
# docker-compose up -d
```

Проверка:

```bash
docker ps
```

---

## 4. Настройка X11 локально (на ноуте) для проброса с сервера

Цель: картинка с сервера (например, окно приложения) показывалась на твоём ноуте.

### 4.1 Windows (ноутбук)

**Важно:** VcXsrv работает **только на твоём ноутбуке (Windows)**. На сервере его ставить и запускать не нужно: на сервере только SSH и приложения (xclock и т.д.), а картинка пробрасывается на ноутбук.

На Windows нет нативного X11. Нужен X-сервер.

**Вариант A — готовая установка VcXsrv (рекомендуется):**

У тебя папка `vcxsrv-master` — это **исходный код**, для запуска нужен **установщик**:

1. Скачай установщик: https://sourceforge.net/projects/vcxsrv/files/latest/download (или страница https://sourceforge.net/projects/vcxsrv/ → Files → скачай `.exe` установщик).
2. Установи VcXsrv (Next → Next).
3. Запусти **XLaunch** (из меню Пуск: "XLaunch" или "VcXsrv XLaunch"):
   - **Step 1:** «Multiple windows» → Next  
   - **Step 2:** «Start no client» → Next  
   - **Step 3:** Поставь галочку **«Disable access control»** (обязательно) → Next → Finish.
4. В том же терминале (PowerShell или CMD), откуда будешь подключаться к серверу, задай переменную:

```powershell
$env:DISPLAY = "localhost:0"
```

5. Подключись к серверу **с пробросом X11** (из той же консоли):

```powershell
ssh -Y user@server_ip
```

6. На сервере после входа запусти тест:

```bash
xclock
```

Окно часов должно открыться **на твоём ноутбуке**. Так ты проверяешь, что картинка с сервера прокидывается.

**Если хочешь собрать VcXsrv из исходников** (папка `vcxsrv-master`): нужны Visual Studio 2022, Cygwin, Perl, см. `HOW_TO_BUILD.txt` в репозитории. Проще использовать готовый установщик с SourceForge.

**Вариант B — WSL2 + WSLg:**  
Если используешь WSL2, в новых версиях Windows уже есть WSLg (X11/Wayland). Тогда:

```bash
ssh -Y user@server_ip
# на сервере
xclock
```

### 4.2 macOS (ноутбук)

Установи XQuartz:

```bash
brew install --cask xquartz
```

Перезапусти сессию (или перелогинься). После запуска XQuartz:

```bash
ssh -Y user@server_ip
```

На сервере:

```bash
xclock
```

### 4.3 Linux (ноутбук)

Обычно X11 уже есть. Подключение:

```bash
ssh -X user@server_ip
# или для доверенного проброса (меньше ограничений)
ssh -Y user@server_ip
```

На сервере:

```bash
xclock
```

---

## 5. Краткий чеклист

| Шаг | Действие |
|-----|----------|
| 1 | На сервере: `apt install xorg x11-xserver-utils x11-apps` |
| 2 | Локально: установить X-сервер (VcXsrv / XQuartz / уже есть на Linux) |
| 3 | Подключиться: `ssh -Y user@server_ip`, на сервере запустить `xclock` — проверить, что окно на ноуте |
| 4 | На сервере: `apt remove x11-apps` (снести программу часов) |
| 5 | На сервере: `ssh-keygen -t ed25519 ...`, скопировать `.pub` в GitHub → Settings → SSH keys |
| 6 | На сервере: настроить `~/.ssh/config` для `github.com`, проверить `ssh -T git@github.com` |
| 7 | На сервере: `git clone git@github.com:egorz-code/SuperCell.git`, `cd SuperCell` |
| 8 | На сервере: `docker compose up -d` |

Если на каком-то шаге будет ошибка — пришли вывод команды и ОС сервера/ноута, подправим под твой случай.

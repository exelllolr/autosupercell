# GoLogin Runner

Запуск сценариев автоматизации через **только SDK GoLogin**; используются **только свои прокси** (Novada или `proxies.txt`), не прокси GoLogin.

## Настройка

### 1. API Token и Profile ID

- **API Token:** личный кабинет GoLogin → иконка профиля (правый верхний угол) → **API Token** → скопировать.
- **Profile ID:** в списке профилей → три точки у нужного профиля → **Copy Profile ID**.

### 2. Переменные окружения

В корне проекта в файле `.env`:

```env
GOLOGIN_API_TOKEN=ваш_токен
GOLOGIN_PROFILE_ID=ваш_profile_id
```

Если эти переменные не заданы, браузер запустится через стандартный Patchright (fallback).

### 3. Прокси (Novada или файл)

Используются только свои прокси из настроек. Включите Novada и задайте учётные данные:

```env
PROXY_ENABLED=true
NOVADA_ENABLED=true
NOVADA_USERNAME=ваш_логин
NOVADA_API_KEY=ваш_ключ
NOVADA_ZONE=res
NOVADA_REGION=us
NOVADA_PROXY_HOST=super.novada.pro
NOVADA_PROXY_PORT=7777
NOVADA_STICKY_MINUTES=8
```

Либо используйте `proxies.txt` (формат `host:port:user:pass` или `user:pass@host:port`).

## Запуск

Из корня проекта:

```bash
# Быстрый прогон: открыть store, скриншот, закрыть
python -m gologin_runner.run
```

Демо с возможной авторизацией (если задан `SUPERCELL_DEMO_EMAIL`):

```bash
# Только store + скриншот
python -m gologin_runner.purchase

# С авторизацией (email и опционально код из письма)
set SUPERCELL_DEMO_EMAIL=your@email.com
set SUPERCELL_DEMO_CODE=123456
python -m gologin_runner.purchase
```

**Демо: ручной вход в аккаунт + покупка + Google Pay (Clash Royale):**

Браузер — только GoLogin SDK; прокси — только свои (Novada при `NOVADA_ENABLED=true` или из `proxies.txt`). По умолчанию: игра Clash Royale, товар «500 Gems», прокси включены.

```bash
python -m gologin_runner.manual_login_gpay_demo_clash_royale
python -m gologin_runner.manual_login_gpay_demo_clash_royale --product "80 Gems"
python -m gologin_runner.manual_login_gpay_demo_clash_royale --product "1200 Gems"
```

Без прокси: добавьте флаг `--no-proxy`.

Процесс: запуск браузера (GoLogin + свой прокси) → открытие store → ручной вход в аккаунт (в консоли нажать Enter) → автоматическая покупка выбранного товара → Checkout → оплата через Google Pay.

В логах при успешном запуске через GoLogin будет строка вида:

```
Запуск браузера через GoLogin (profile: xxxxxxxx...)
```

## Зависимости

Установка пакета GoLogin (уже добавлен в `requirements.txt`):

```bash
pip install gologin
```

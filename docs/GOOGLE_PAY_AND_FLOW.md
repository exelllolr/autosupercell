# Google Pay и «весь путь через Google»

## Полный путь оплаты (по шагам)

Оплата через Google Pay может открывать **два варианта** формы входа. Скрипт обрабатывает оба.

### Вариант A: Popup-окно «Sign in - Google Accounts»

1. **Магазин** → Checkout → открывается страница FastSpring (например `pay.fastspring.com/.../googlepay.html`) с кнопкой **«Pay with G Pay»**.
2. Пользователь (или скрипт) нажимает **«Pay with G Pay»**.
3. Открывается **отдельное окно** (popup) с заголовком **«Sign in - Google Accounts»** и URL `accounts.google.com/v3/signin/identifier?...`.
4. В этом окне: поле **«Email or phone»** / «Телефон или адрес эл. почты» → **Next** / **Далее** → пароль → при необходимости 2FA (backup code).
5. После входа popup переходит к подтверждению оплаты; по завершении окно закрывается или возвращается на страницу оплаты.
6. Итог: **«CONGRATULATIONS PURCHASE COMPLETE»** (или аналог) → скриншоты, проверка аккаунта, отвязка карты при необходимости.

Скрипт **сначала** ждёт появления такого popup (до 45 сек) и переключается на него; логин выполняется на **основной странице** этого окна (без iframe).

### Вариант B: Форма в том же окне (iframe payframe)

1. То же: магазин → Checkout → страница FastSpring с **«Pay with G Pay»**.
2. После клика по **«Pay with G Pay»** **отдельное окно accounts.google.com не открывается**; форма входа появляется **в том же окне** во **iframe** (payframe, `pay.google.com/gp/p/ui`).
3. Скрипт ждёт появления iframe payframe и вводит email/пароль через **frame_locator** (из-за cross-origin).
4. Далее: Next → пароль → 2FA при необходимости → подтверждение оплаты.
5. Итог так же: завершение покупки, скриншоты, проверка, отвязка.

### Общая последовательность (независимо от варианта)

| Шаг | Действие |
|-----|----------|
| 1 | Store (Supercell) → корзина → Checkout. |
| 2 | Открывается FastSpring (вкладка/окно): выбор способа оплаты → вкладка **G Pay** → кнопка **«Place Your Order»** (или аналог). |
| 3 | Страница `pay.fastspring.com/.../googlepay.html`: корзина, кнопка **«Pay with G Pay»**. |
| 4 | Клик **«Pay with G Pay»** → либо **popup** (accounts.google.com), либо форма в **iframe** в том же окне. |
| 5 | Вход в Google: email → Next → пароль (App Password) → при запросе 2FA — «Try another way» → «Enter one of your 8-digit backup codes» → ввод кода. |
| 6 | Подтверждение оплаты в окне Google Pay. |
| 7 | Ожидание «Processing Payment» / «CONGRATULATIONS PURCHASE COMPLETE». |
| 8 | Скриншоты, проверка аккаунта, при необходимости отвязка способа оплаты. |

---

## Можно ли взять Google API и пройти весь путь через Google?

**Кратко: нет.** Для нашей задачи (покупатель на Supercell Store) **официального Google API для программной оплаты со стороны покупателя нет**.

### Почему так

- **Google Pay API** ( [developers.google.com/pay](https://developers.google.com/pay/api/web/overview) ) предназначен для **мерчантов** (сайтов). Мерчант встраивает кнопку «Pay with Google Pay» и получает от Google **платёжный токен** после того, как **пользователь в браузере** нажал кнопку и подтвердил оплату.
- Мы выступаем как **покупатель** на чужом сайте (FastSpring / Supercell). Оплата инициируется на стороне мерчанта; мы не можем «вызвать Google API с сервера» и оплатить за пользователя — такого публичного API для покупателя нет (и это было бы небезопасно).
- Поэтому единственный вариант — автоматизировать **тот же путь, что и человек**: браузер → магазин → Checkout → вкладка G Pay → кнопка «Place Your Order» → **popup Google** → вход (email + App Password / 2FA) → подтверждение оплаты. Это мы уже делаем в `app/core/google_pay.py`.

### Что мы уже используем «через Google»

| Этап | Как реализовано |
|------|------------------|
| Вход в аккаунт Supercell | Свой логин (email + код), не Google. |
| Оплата на FastSpring | Вкладка **G Pay** → кнопка оплаты → открывается **popup Google**. |
| Вход в Google (popup) | Автоматический ввод **email** и **App Password** из `.env`. |
| 2FA (если просит Google) | Резервные 8-значные коды из `GOOGLE_BACKUP_CODES` в `.env`. |
| Подтверждение оплаты | Ожидание и клики в popup до «CONGRATULATIONS PURCHASE COMPLETE». |

То есть **весь путь до оплаты уже идёт через Google** в том смысле, что финальный шаг — именно Google Pay popup и вход в Google в браузере. Заменить этот шаг на «один вызов Google API с бэкенда» нельзя.

---

## Проксирование: трафик к Google — напрямую к серверам Google

Чтобы не ловить **ERR_TUNNEL_CONNECTION_FAILED** в popup Google (логин / G Pay), трафик к доменам Google можно не пускать через прокси: он пойдёт **напрямую к серверам Google**.

- **Store / FastSpring** — через ваш прокси (Bright Data и т.д.).
- **Google (accounts.google.com, pay, gstatic, youtube)** — без прокси, прямо на сервера Google.

Включено по умолчанию. В `.env` можно задать свой список доменов для обхода (через запятую):

```env
# По умолчанию уже задано в коде; переопределить при необходимости:
PROXY_BYPASS_GOOGLE=*.google.com,*.googleapis.com,*.gstatic.com,*.youtube.com
```

Чтобы отключить обход (весь трафик через прокси), задайте пустое значение:

```env
PROXY_BYPASS_GOOGLE=
```

---

## Как это раскатить (настройка и запуск)

### 1. Настройка Google для автоматизации

1. **Аккаунт Google**  
   Используйте тот же аккаунт, с которого вы обычно платите в Google Pay.

2. **App Password (обязательно)**  
   - Зайдите: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).  
   - Создайте пароль приложения (тип «Почта и другие приложения» или «Другое»).  
   - Скопируйте 16-символьный пароль (без пробелов).

3. **Резервные коды (2FA)**  
   Если включена двухфакторная аутентификация, при первом входе в popup Google может потребоваться код:  
   - [myaccount.google.com/signinoptions/two-step-verification](https://myaccount.google.com/signinoptions/two-step-verification) → «Резервные коды» → сгенерировать и сохранить.  
   - В форме 2-Step Verification скрипт сам нажимает **«Try another way»**, затем **«Enter one of your 8-digit backup codes»**, после чего вводит первый код из `GOOGLE_BACKUP_CODES`. Ручной выбор этой опции не нужен — достаточно указать коды в `.env`.

### 2. Переменные в `.env`

```env
# Оплата через Google Pay
GOOGLE_PAY_ENABLED=true
GOOGLE_EMAIL=ваш@gmail.com
GOOGLE_APP_PASSWORD=xxxx xxxx xxxx xxxx
GOOGLE_BACKUP_CODES=12345678,87654321
PAYMENT_TIMEOUT=420
```

- `GOOGLE_EMAIL` — Gmail, привязанный к Google Pay.  
- `GOOGLE_APP_PASSWORD` — пароль приложения (можно с пробелами, скрипт их убирает).  
- `GOOGLE_BACKUP_CODES` — один или несколько 8-значных кодов через запятую (на случай 2FA в popup).

### 3. Запуск сценария (демо)

```bash
# Clash Royale, товар «80 Gems», с прокси из .env
python examples/manual_login_gpay_demo_clash_royale.py --product "80 Gems"
```

Процесс: браузер с прокси → store.supercell.com → вы вручную входите в Supercell → после Enter скрипт идёт в магазин игры → корзина → Checkout → вкладка G Pay → «Place Your Order» → **автовход в Google (email + App Password / backup code)** → ожидание завершения оплаты.

### 4. Через API (покупка по заказу)

Эндпоинты в `app/api/store_routes.py` используют тот же `handle_google_pay` из `app/core/google_pay.py`: после открытия Checkout на FastSpring скрипт выбирает G Pay и проходит popup Google так же, как в демо.

Для продакшена:

- Не храните `GOOGLE_EMAIL` / `GOOGLE_APP_PASSWORD` / `GOOGLE_BACKUP_CODES` в репозитории.  
- Используйте секреты окружения или секрет-менеджер (Docker secrets, Kubernetes secrets, переменные CI/CD и т.д.).  
- `.env` должен быть в `.gitignore` (как в проекте).

### 5. Если Google блокирует вход («This browser or app may not be secure»)

- Один раз войдите в этот же Google-аккаунт **вручную** в том же профиле браузера, который использует скрипт (`browser_profile` или системный Chrome при `BROWSER_USE_SYSTEM_PROFILE=true`).  
- После успешного ручного входа часто достаточно снова запустить демо/API — автоматический вход в popup начинает проходить стабильнее.  
- Дополнительно можно включить Patchright и не headless: в `.env` например `BROWSER_USE_PATCHRIGHT=true`, `BROWSER_HEADLESS=false`, `BROWSER_USE_CHROME=true`.

---

## Итог

- **«Взять API Google и пройти весь путь через Google»** в смысле «одна серверная интеграция с Google вместо браузера» — **нельзя**: для покупателя на стороннем сайте (Supercell/FastSpring) оплата возможна только через браузерный flow (G Pay popup + вход в Google).  
- **Текущая реализация уже идёт «через Google»**: автоматизация входа в Google (email + App Password + при необходимости backup code) и подтверждения оплаты в popup.  
- **Раскатка**: настроить `.env` (Google email, App Password, backup codes), при необходимости один раз войти вручную в том же профиле, затем запускать демо или API; в проде — хранить секреты в переменных окружения/секрет-менеджере.

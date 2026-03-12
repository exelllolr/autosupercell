# Логи сети и консоли на сервере (аналог DevTools)

Чтобы понять, почему на сервере не появляется кнопка (например «Pay with G Pay») или падает запрос, можно смотреть те же данные, что и во вкладке Network/Console в DevTools.

## 1. Вывод в stdout (логи приложения)

При `BROWSER_NETWORK_LOG=true` и `BROWSER_CONSOLE_LOG=true` (по умолчанию) в лог пишутся:

- **Ошибки сети:** `✗ [GET] FAILED https://... - net::ERR_...`, `← [403] GET https://...`
- **Ошибки консоли:** `CONSOLE ERROR: ...`, `PAGE ERROR (uncaught): ...`

На сервере смотрите логи контейнера/сервиса (например `docker compose logs -f`, или журнал systemd). Уровень логирования: **INFO** и выше (ошибки уже попадают в INFO).

## 2. Сохранение в файл (удобно на сервере)

Задайте путь к файлу — в него дописываются только **ошибки** (failed requests, 4xx/5xx, console error, page error):

```env
BROWSER_SAVE_NETWORK_LOG_PATH=logs/network_console.log
```

После прогона на сервере:

```bash
cat logs/network_console.log
# или
tail -100 logs/network_console.log
```

Файл создаётся в корне проекта (или по абсолютному пути). Каждая строка в формате:

```
[2026-03-11 12:34:56] [popup] ✗ [GET] FAILED https://pay.google.com/... - net::ERR_BLOCKED_BY_CLIENT
[2026-03-11 12:34:57] [main] CONSOLE ERROR: Failed to load resource
```

- **main** — основная вкладка (магазин).
- **popup** — всплывающее окно (в т.ч. Google Pay). Для него тоже пишутся запросы и консоль, так что видно, какой запрос не прошёл в окне оплаты.

## 3. Что проверить по логам

- `FAILED` / `net::ERR_` — запрос не дошёл (блокировка, прокси, CORS, таймаут).
- `← [403]` / `← [404]` — сервер отдал ошибку (часто блок по гео/боту).
- `CONSOLE ERROR` / `PAGE ERROR` — скрипт на странице упал (может мешать появлению кнопки).

При необходимости добавьте в `.gitignore` строку `logs/network_console.log`, чтобы не коммитить логи.

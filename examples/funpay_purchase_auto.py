"""
Автономный скрипт обработки заказов FunPay.

Алгоритм:
  1. Проверяет доступность API (/health)
  2. Проверяет golden_key FunPay (/whoami)
  3. В бесконечном цикле:
       a. Получает список оплаченных заказов FunPay
       b. По каждому заказу:
            - пропускает уже обработанные (Redis или локальный set)
            - при первом обнаружении → отправляет покупателю инструкцию
            - загружает чат
            - парсит: email, OTP, игра, товар
            - если email нет → сообщает покупателю, пропускает
            - если OTP нет → просит покупателя прислать код
            - вызывает POST /api/v1/supercell/purchase
            - по результату → update_order_status в FunPay
       c. sleep(POLL_INTERVAL) и повтор

Запуск:
    python examples/funpay_purchase_auto.py

Переменные окружения (см. .env.example):
    AUTOSUPERCELL_API_URL   — URL сервера (по умолчанию http://localhost:8000/api/v1)
    AUTOSUPERCELL_API_KEY   — X-API-Key (если включён API_SECRET_KEY)
    FUNPAY_GOLDEN_KEY       — golden_key из cookies FunPay
    FUNPAY_EMAIL_PASSWORD   — опционально: пароль от почты покупателя (если вы сами настраиваете)
    POLL_INTERVAL           — интервал опроса в секундах (по умолчанию 45)
    OTP_WAIT_SECONDS        — сколько ждать OTP от покупателя (по умолчанию 240 = 4 мин)
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
load_dotenv("/root/autosupercell/.env")
import time
from pathlib import Path
from typing import Dict, Optional, Set

import requests
from loguru import logger

# Добавляем корень проекта в sys.path чтобы импортировать app.*
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.integrations.funpay import FunPayClient
from app.integrations.funpay_chat_parser import funpay_chat_parser

# ──────────────────────────── конфигурация ───────────────────────────────────

API_URL = os.environ.get("AUTOSUPERCELL_API_URL", "http://localhost:8000/api/v1")
API_KEY = os.environ.get("AUTOSUPERCELL_API_KEY", "")
FUNPAY_GOLDEN_KEY = os.environ.get("FUNPAY_GOLDEN_KEY", "")
FUNPAY_EMAIL_PASSWORD = os.environ.get("FUNPAY_EMAIL_PASSWORD", "")  # опционально
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "45"))
OTP_WAIT_SECONDS = int(os.environ.get("OTP_WAIT_SECONDS", "240"))
REQUEST_TIMEOUT = 720  # чуть больше таймаута сервера (600 сек)

# ──────────────────────────── состояние ──────────────────────────────────────

# Заказы, для которых мы уже попросили OTP (ждём ответа)
_awaiting_otp: Dict[str, float] = {}   # order_id → timestamp запроса

# Обработанные заказы (чтобы не дублировать при рестарте — будет пересоздан)
_processed_orders: Set[str] = set()

# Заказы, которым уже отправлено приветственное сообщение с инструкцией
_greeted_orders: Set[str] = set()

# ──────────────────────────── тексты сообщений ───────────────────────────────

GREETING_MESSAGE = (
    "Привет! Спасибо, что выбрал нас 🙂\n\n"
    "Это автоматическое сообщение.\n\n"
    "Чтобы начать выполнять твой заказ, нам нужно получить данные от твоего аккаунта Supercell:\n"
    "1. Почта (логин)\n"
    "2. Одноразовый код (OTP) для входа\n\n"
    "🔐 Как получить OTP-код? Есть два простых способа:\n\n"
    "Вариант 1 (через сайт):\n"
    "1. Перейди по ссылке: https://accounts.supercell.com/login\n"
    "2. Введи почту от аккаунта, в который нужно приобрести товар.\n"
    "3. На эту почту придет письмо с кодом. Этот код и нужно будет отдать нам.\n\n"
    "Вариант 2 (через игру):\n"
    "1. Зайди в игру.\n"
    "2. В настройках смени аккаунт на тот, на котором будем производить оплату.\n"
    "3. Если ты уже в этом аккаунте — выходить не нужно, просто вызови меню входа "
    "и введи ту же почту для получения кода.\n"
    "4. Появится меню с полем для ввода кода. Выходить из этого меню до момента оплаты нельзя!\n\n"
    "⚠️ Важные правила (прочитай внимательно!):\n"
    "* До того, как товар будет оплачен, заходить в аккаунт нельзя. Ни на телефоне, ни в браузере. "
    "Это касается и ввода полученного кода на своем устройстве — мы должны сделать это первыми.\n"
    "* Полученный код действителен всего 5–10 минут.\n"
    "* Пока я не попрошу — ничего делать не нужно. Не запрашивай код заранее, "
    "иначе он устареет к моменту работы.\n\n"
    "📩 Как только я напишу \"Нужны данные\", просто отправь их одним сообщением в таком формате:\n"
    "`почта@gmail.com 123456`\n"
    "(Сначала почта, потом пробел, потом код для входа)"
)

# ──────────────────────────── HTTP helpers ───────────────────────────────────

def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def _check_api_health() -> bool:
    """Проверить доступность API сервера."""
    try:
        r = requests.get(f"{API_URL}/health", timeout=20, headers=_headers())
        return r.status_code == 200
    except Exception:
        return False


def _call_purchase(
    email: str,
    game: str,
    product_name: str,
    product_type: str,
    verification_code: Optional[str] = None,
    email_password: Optional[str] = None,
) -> Optional[Dict]:
    """
    Вызвать POST /supercell/purchase (синхронно).
    Возвращает dict с результатом или None при ошибке сети.
    """
    payload = {
        "email": email,
        "game": game,
        "product_name": product_name,
        "product_type": product_type,
    }
    if verification_code:
        payload["verification_code"] = verification_code
    if email_password:
        payload["email_password"] = email_password

    # Не логируем email_password
    safe_payload = {k: ("***" if k == "email_password" else v) for k, v in payload.items()}
    logger.info(f"→ POST /supercell/purchase: {safe_payload}")

    try:
        resp = requests.post(
            f"{API_URL}/supercell/purchase",
            json=payload,
            timeout=REQUEST_TIMEOUT,
            headers=_headers(),
        )
        return resp.json() if resp.content else {"success": False, "error": f"HTTP {resp.status_code}"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Таймаут запроса (> 10 мин)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ──────────────────────────── обработка заказа ───────────────────────────────

async def process_order(client: FunPayClient, order: Dict) -> None:
    """
    Полный цикл обработки одного заказа FunPay.
    """
    order_id = order["order_id"]
    logger.info(f"━━ Заказ {order_id}: '{order.get('title', '')}' — покупатель: {order.get('buyer_name', '')}")

    # ── Шаг 0: Приветственное сообщение при первом обнаружении заказа ─────────
    if order_id not in _greeted_orders:
        sent = await client.send_chat_message(order_id, GREETING_MESSAGE)
        if sent:
            logger.info(f"Заказ {order_id}: приветственное сообщение с инструкцией отправлено")
            _greeted_orders.add(order_id)
        else:
            logger.warning(f"Заказ {order_id}: не удалось отправить приветствие, повторим в следующем цикле")
        # Даём покупателю время прочитать инструкцию перед следующими шагами
        await asyncio.sleep(3)

    # 1. Загружаем детали + чат
    detail = await client.get_order_detail(order_id)
    if not detail:
        logger.error(f"Заказ {order_id}: не удалось загрузить детали")
        return

    messages = detail.get("messages", [])
    logger.info(f"Заказ {order_id}: загружено {len(messages)} сообщений чата")

    # 2. Парсим данные
    parsed = funpay_chat_parser.parse(
        order=detail,
        messages=messages,
        email_password=FUNPAY_EMAIL_PASSWORD,
    )

    game = parsed["game"]
    product_name = parsed["product_name"]
    product_type = parsed["product_type"]
    email = parsed["email"]
    verification_code = parsed["verification_code"]
    email_password = parsed["email_password"]
    otp_age = parsed["otp_age_seconds"]
    errors = parsed["errors"]

    if errors:
        logger.warning(f"Заказ {order_id} — предупреждения парсера: {'; '.join(errors)}")

    # 3. Проверяем email
    if not email:
        logger.warning(f"Заказ {order_id}: email не найден — просим покупателя")
        await client.send_chat_message(
            order_id,
            "👋 Добрый день! Для выполнения заказа, пожалуйста, укажите в чате:\n"
            "1️⃣ Email вашего Supercell аккаунта\n"
            "2️⃣ После этого пришлите 6-значный код из письма Supercell",
        )
        # Помечаем как ожидание (повторим опрос позже)
        _awaiting_otp[order_id] = time.time()
        return

    # 4. Проверяем OTP
    if not verification_code and not email_password:
        # Проверяем: уже просили код?
        asked_at = _awaiting_otp.get(order_id)

        if asked_at is None:
            # Первый раз просим OTP
            logger.info(f"Заказ {order_id}: OTP не найден — просим покупателя прислать код")
            await client.send_chat_message(
                order_id,
                f"✅ Email {email} принят.\n"
                "📧 Пожалуйста, отправьте на этот email запрос на вход в Supercell Store "
                "и пришлите сюда 6-значный код верификации из письма.",
            )
            _awaiting_otp[order_id] = time.time()
            return

        # Уже просили — проверяем таймаут ожидания
        waited = time.time() - asked_at
        if waited < OTP_WAIT_SECONDS:
            logger.info(f"Заказ {order_id}: ждём OTP от покупателя ({waited:.0f}/{OTP_WAIT_SECONDS} сек)")
            return
        else:
            # Покупатель не ответил — фейлим заказ
            logger.error(f"Заказ {order_id}: OTP не получен за {OTP_WAIT_SECONDS} сек")
            await client.update_order_status(
                order_id,
                "failed",
                {"error": f"Покупатель не предоставил код верификации за {OTP_WAIT_SECONDS} сек"},
            )
            _processed_orders.add(order_id)
            _awaiting_otp.pop(order_id, None)
            return

    # Очищаем флаг ожидания
    _awaiting_otp.pop(order_id, None)

    # 5. Предупреждение об устаревшем OTP
    if verification_code and otp_age is not None and otp_age > 270:
        logger.warning(f"Заказ {order_id}: OTP возраст {otp_age:.0f} сек — может быть просрочен")

    # 6. Вызываем покупку (синхронно в executor чтобы не блокировать event loop)
    logger.info(
        f"Заказ {order_id}: запускаем покупку — "
        f"game={game}, product={product_name}, email={email}, "
        f"otp={'✓' if verification_code else 'через_email'}"
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _call_purchase(
            email=email,
            game=game,
            product_name=product_name,
            product_type=product_type,
            verification_code=verification_code,
            email_password=email_password if not verification_code else None,
        ),
    )

    if result is None:
        logger.error(f"Заказ {order_id}: нет ответа от API (network error)")
        await client.send_chat_message(order_id, "⚠️ Ошибка связи с сервером. Повторяем попытку через минуту.")
        # Не помечаем как обработанный — повторим на следующем цикле
        return

    # 7. Обрабатываем результат
    success = result.get("success", False)
    error = result.get("error") or result.get("message") or ""
    proof = {
        "message": result.get("message", ""),
        "url": result.get("url", ""),
        "screenshot": result.get("screenshot", ""),
        "checkout_screenshot": result.get("checkout_screenshot", ""),
    }
    payment = result.get("payment", {})
    if payment:
        proof["payment_confirmed"] = payment.get("payment_confirmed", False)
        proof["payment_verified"] = payment.get("payment_verified", False)

    if success:
        logger.success(f"✅ Заказ {order_id} выполнен: {result.get('message', '')}")
        await client.update_order_status(order_id, "completed", proof)
        _processed_orders.add(order_id)
    else:
        # Проверяем: ошибка неверного OTP?
        otp_error_keywords = ("invalid code", "неверный код", "code expired", "wrong code",
                               "verification", "код", "истек", "повторите")
        is_otp_error = any(kw in error.lower() for kw in otp_error_keywords)

        if is_otp_error and verification_code:
            logger.warning(f"❌ Заказ {order_id}: OTP неверный — просим новый код у покупателя")
            # Сбрасываем флаг ожидания чтобы на следующем цикле запросить новый код
            _awaiting_otp.pop(order_id, None)
            await client.send_chat_message(
                order_id,
                "❌ Код верификации не подошёл или устарел.\n"
                "Пожалуйста, запросите новый код входа в Supercell и пришлите его сюда.\n"
                "⚠️ Код действует только 5 минут — присылайте сразу после получения письма."
            )
            # НЕ помечаем как обработанный — будем ждать новый OTP
        else:
            logger.error(f"❌ Заказ {order_id} провалился: {error}")
            await client.update_order_status(order_id, "failed", {"error": error, **proof})
            _processed_orders.add(order_id)


# ──────────────────────────── главный цикл ───────────────────────────────────

async def main_loop() -> None:
    """Основной цикл обработки заказов FunPay."""

    # ── Проверка переменных ───────────────────────────────────────────────────
    if not FUNPAY_GOLDEN_KEY:
        logger.error(
            "FUNPAY_GOLDEN_KEY не задан!\n"
            "Добавьте в .env: FUNPAY_GOLDEN_KEY=<ваш_ключ>\n"
            "Ключ находится в cookie 'golden_key' на funpay.com (DevTools → Application → Cookies)"
        )
        sys.exit(1)

    # ── Проверка API ──────────────────────────────────────────────────────────
    logger.info(f"Проверка API сервера: {API_URL}/health")
    if not _check_api_health():
        logger.error(
            f"API сервер недоступен: {API_URL}\n"
            "Запустите сервер: docker-compose up -d  или  uvicorn app.main:app"
        )
        sys.exit(1)
    logger.success("✅ API сервер доступен")

    # ── Проверка golden_key ───────────────────────────────────────────────────
    client = FunPayClient(FUNPAY_GOLDEN_KEY)
    try:
        me = await client.whoami()
        if me:
            logger.success(f"✅ FunPay: авторизован как {me.get('username')} (id={me.get('user_id')})")
        else:
            logger.error(
                "❌ FunPay: не удалось получить данные аккаунта.\n"
                "Проверьте FUNPAY_GOLDEN_KEY — возможно ключ устарел или неверный."
            )
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ FunPay подключение: {e}")
        sys.exit(1)

    logger.info(
        f"\n{'='*60}\n"
        f"FunPay Auto Purchase запущен\n"
        f"Интервал опроса: {POLL_INTERVAL} сек\n"
        f"Ожидание OTP: {OTP_WAIT_SECONDS} сек\n"
        f"{'='*60}"
    )

    # ── Главный цикл ─────────────────────────────────────────────────────────
    consecutive_errors = 0

    while True:
        try:
            # Получаем оплаченные заказы
            orders = await client.get_orders(status="paid")
            logger.info(f"FunPay: {len(orders)} активных заказов")

            for order in orders:
                order_id = order["order_id"]

                # Пропускаем уже обработанные
                if order_id in _processed_orders:
                    continue

                try:
                    await process_order(client, order)
                except Exception as e:
                    logger.exception(f"Ошибка обработки заказа {order_id}: {e}")
                    # Не прерываем цикл — переходим к следующему заказу

                # Небольшая пауза между заказами
                await asyncio.sleep(2)

            consecutive_errors = 0

        except Exception as loop_err:
            consecutive_errors += 1
            logger.error(f"Ошибка в главном цикле (#{consecutive_errors}): {loop_err}")

            if consecutive_errors >= 10:
                logger.critical(
                    "10 последовательных ошибок — возможно проблема с сессией FunPay. "
                    "Попробуйте обновить FUNPAY_GOLDEN_KEY."
                )
                # Не завершаем процесс, продолжаем с увеличенной паузой
                await asyncio.sleep(POLL_INTERVAL * 3)
                continue

        logger.debug(f"Следующий опрос через {POLL_INTERVAL} сек...")
        await asyncio.sleep(POLL_INTERVAL)


# ──────────────────────────── точка входа ────────────────────────────────────

if __name__ == "__main__":
    # Настройка логирования
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
        level=log_level,
        colorize=True,
    )
    logger.add(
        "logs/funpay_auto.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )

    print("=" * 60)
    print("  FunPay Auto Purchase — автономный обработчик заказов")
    print("=" * 60)

    if API_KEY:
        masked = "*" * (len(API_KEY) - 4) + API_KEY[-4:]
        print(f"  API-ключ: {masked}")
    else:
        print("  API-ключ: не задан")

    golden_preview = FUNPAY_GOLDEN_KEY[:6] + "..." if FUNPAY_GOLDEN_KEY else "НЕ ЗАДАН"
    print(f"  FunPay golden_key: {golden_preview}")
    print()

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("\n⚠️  Остановлено пользователем (Ctrl+C)")
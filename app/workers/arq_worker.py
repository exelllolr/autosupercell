"""ARQ worker для обработки заказов в фоне."""

from arq.connections import RedisSettings
from loguru import logger

from app.config import settings
from app.integrations.avito import avito_integration
from app.integrations.funpay import funpay_integration
from app.integrations.kupikod import kupikod_integration
from app.integrations.plati import plati_integration
from app.services.order_processor import OrderProcessor


async def process_order_task(ctx: dict, order_data: dict) -> dict:
    """
    Задача обработки заказа.

    Args:
        ctx: Контекст задачи (содержит redis, job_id и т.д.)
        order_data: Данные заказа

    Returns:
        Результат обработки
    """
    order_id = order_data.get("order_id", "unknown")
    job_id = ctx.get("job_id", "unknown")
    retry = ctx.get("job_try", 1)

    logger.info(
        "Начало обработки задачи заказа: %s (job_id=%s, попытка %d/%d)",
        order_id,
        job_id,
        retry,
        WorkerSettings.max_tries,
    )

    try:
        processor = OrderProcessor()
        result = await processor.process_order(order_data)
    except Exception as exc:
        logger.error(
            "Необработанное исключение в process_order_task "
            "(order_id=%s, попытка %d): %s",
            order_id,
            retry,
            exc,
        )
        # Пробрасываем, чтобы ARQ мог выполнить повтор (если попыток ещё хватает)
        raise

    # Отправляем результат обратно в интеграцию только при финальном успехе
    source = order_data.get("source", "unknown")

    if result.get("success"):
        proof_data = result.get("proof", {})
        try:
            if source == "plati":
                await plati_integration.update_order_status(
                    order_id, "completed", proof_data
                )
            elif source == "kupikod":
                await kupikod_integration.send_proof(order_id, proof_data)
            elif source == "funpay":
                await funpay_integration.update_order_status(
                    order_id, "completed", proof_data
                )
            elif source == "avito":
                await avito_integration.update_order_status(
                    order_id, "completed", proof_data
                )
        except Exception as notify_exc:
            # Уведомление не критично — результат уже есть, просто логируем
            logger.warning(
                "Не удалось отправить уведомление в интеграцию '%s' для заказа %s: %s",
                source,
                order_id,
                notify_exc,
            )
    else:
        logger.warning(
            "Заказ %s завершён без успеха (source=%s): %s",
            order_id,
            source,
            result.get("message", "нет сообщения"),
        )

    logger.info(
        "Задача заказа %s завершена (success=%s)", order_id, result.get("success")
    )
    return result


# ─── Хуки жизненного цикла задачи ────────────────────────────────────────────


async def on_job_start(ctx: dict) -> None:
    """Вызывается ARQ перед стартом каждой задачи."""
    logger.info(
        "ARQ: задача стартовала (job_id=%s, функция=%s, попытка %d)",
        ctx.get("job_id"),
        ctx.get("job_name"),
        ctx.get("job_try", 1),
    )


async def on_job_end(ctx: dict) -> None:
    """Вызывается ARQ после завершения каждой задачи."""
    logger.info(
        "ARQ: задача завершена (job_id=%s, функция=%s)",
        ctx.get("job_id"),
        ctx.get("job_name"),
    )


async def on_job_abort(ctx: dict) -> None:
    """Вызывается ARQ при прерывании/аборте задачи."""
    logger.error(
        "ARQ: задача прервана (job_id=%s, функция=%s, попытка %d)",
        ctx.get("job_id"),
        ctx.get("job_name"),
        ctx.get("job_try", 1),
    )


async def startup(ctx: dict) -> None:
    """Инициализация воркера при запуске."""
    logger.info(
        "ARQ worker запущен (redis=%s:%s)", settings.REDIS_HOST, settings.REDIS_PORT
    )


async def shutdown(ctx: dict) -> None:
    """Завершение воркера при остановке."""
    logger.info("ARQ worker остановлен")


# ─── Настройки воркера ────────────────────────────────────────────────────────


class WorkerSettings:
    """Настройки ARQ worker."""

    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        database=settings.REDIS_DB,
    )

    functions = [process_order_task]

    # Максимальное количество одновременных задач
    max_jobs = 10

    # Таймаут одной задачи (10 минут — соответствует REQUEST_TIMEOUT в purchase_demo)
    job_timeout = 600

    # Повторные попытки при сбое: задача будет запущена повторно до 3 раз
    # (включая первую — итого максимум 3 попытки)
    max_tries = 3

    # Хранить результат задачи в Redis 1 час после завершения
    # (чтобы GET /orders/{id}/status мог вернуть финальный результат)
    keep_result = 3600  # секунд

    # Хранить результат провальной задачи (после исчерпания всех попыток)
    keep_result_forever = False

    # Хуки жизненного цикла
    on_job_start = on_job_start
    on_job_end = on_job_end
    on_job_abort = on_job_abort

    on_startup = startup
    on_shutdown = shutdown


# WorkerSettings используется для запуска через arq CLI:
#   arq app.workers.arq_worker.WorkerSettings
#
# Или через run_worker.py:
#   python run_worker.py

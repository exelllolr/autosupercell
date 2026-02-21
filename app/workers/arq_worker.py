"""ARQ worker для обработки заказов в фоне."""

import asyncio
from typing import Dict
from arq import create_pool
from arq.connections import RedisSettings
from loguru import logger
from app.config import settings
from app.services.order_processor import OrderProcessor
from app.integrations.plati import plati_integration
from app.integrations.kupikod import kupikod_integration
from app.integrations.funpay import funpay_integration
from app.integrations.avito import avito_integration


async def process_order_task(ctx: Dict, order_data: Dict) -> Dict:
    """
    Задача обработки заказа.

    Args:
        ctx: Контекст задачи
        order_data: Данные заказа

    Returns:
        Результат обработки
    """
    logger.info(f"Начало обработки задачи заказа: {order_data.get('order_id')}")

    processor = OrderProcessor()
    result = await processor.process_order(order_data)

    # Отправляем результат обратно в интеграцию
    order_id = order_data.get("order_id")
    source = order_data.get("source", "unknown")

    if result.get("success"):
        proof_data = result.get("proof", {})
        # Обновляем статус в соответствующей интеграции
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

    return result


class WorkerSettings:
    """Настройки ARQ worker."""

    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        database=settings.REDIS_DB,
    )

    functions = [process_order_task]

    max_jobs = 10
    job_timeout = 600  # 10 минут максимум


# WorkerSettings используется для запуска через arq CLI:
# arq app.workers.arq_worker.WorkerSettings

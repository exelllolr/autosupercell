"""API routes для обработки заказов."""

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel
from typing import Optional, Dict
from loguru import logger
from arq import create_pool
from arq.connections import RedisSettings
from app.config import settings
from app.core.proxy_manager import proxy_manager
from app.integrations.kupikod import kupikod_integration
from app.integrations.plati import plati_integration
from app.integrations.funpay import funpay_integration
from app.integrations.avito import avito_integration

router = APIRouter()


class OrderRequest(BaseModel):
    """Модель запроса на обработку заказа."""

    order_id: str
    product_name: str
    product_type: str = "gems"
    game: str = "clash-royale"
    amount: float
    currency: str = "USD"
    user_account: str
    payment_method: str = "google_pay"
    card_info: Dict


class WebhookRequest(BaseModel):
    """Модель webhook запроса."""

    order_id: str
    product_name: str
    product_type: Optional[str] = "gems"
    game: Optional[str] = "clash-royale"
    amount: float
    currency: Optional[str] = "USD"
    user_account: str
    payment_method: Optional[str] = "google_pay"
    card_info: Dict


@router.post("/orders/process")
async def process_order(order: OrderRequest, source: str = "manual"):
    """
    Обработать заказ напрямую через API.

    Args:
        order: Данные заказа
        source: Источник заказа (plati, kupikod, funpay, avito, manual)

    Returns:
        Результат постановки в очередь
    """
    try:
        # Создаем пул Redis для ARQ
        redis_pool = await create_pool(
            RedisSettings(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                database=settings.REDIS_DB,
            )
        )

        # Формируем данные задачи
        order_data = order.dict()
        order_data["source"] = source

        # Ставим задачу в очередь
        job = await redis_pool.enqueue_job(
            "process_order_task", order_data, _job_id=f"order_{order.order_id}"
        )

        logger.info(f"Заказ {order.order_id} поставлен в очередь: {job.job_id}")

        return {
            "success": True,
            "order_id": order.order_id,
            "job_id": job.job_id,
            "status": "queued",
        }

    except Exception as e:
        logger.error(f"Ошибка обработки заказа: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhooks/kupikod")
async def kupikod_webhook(
    request: Request,
    payload: WebhookRequest,
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    """
    Webhook от Kupikod.

    Args:
        request: HTTP запрос
        payload: Тело webhook
        x_signature: Подпись webhook

    Returns:
        Результат обработки webhook
    """
    try:
        # Проверяем подпись
        body = await request.body()
        if x_signature and not kupikod_integration.verify_webhook(
            body.decode(), x_signature
        ):
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Парсим webhook
        order_data = kupikod_integration.parse_webhook(payload.dict())
        if not order_data:
            raise HTTPException(status_code=400, detail="Invalid webhook payload")

        order_data["source"] = "kupikod"

        # Ставим в очередь
        redis_pool = await create_pool(
            RedisSettings(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                database=settings.REDIS_DB,
            )
        )

        job = await redis_pool.enqueue_job(
            "process_order_task",
            order_data,
            _job_id=f"order_{order_data['order_id']}",
        )

        logger.info(f"Webhook от Kupikod обработан: {order_data['order_id']}")

        return {
            "success": True,
            "order_id": order_data["order_id"],
            "job_id": job.job_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка обработки webhook Kupikod: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/{order_id}/status")
async def get_order_status(order_id: str):
    """
    Получить статус заказа.

    Args:
        order_id: ID заказа

    Returns:
        Статус заказа
    """
    try:
        import redis.asyncio as redis

        # Подключаемся к Redis для проверки статуса
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            db=settings.REDIS_DB,
            decode_responses=True,
        )

        job_id = f"order_{order_id}"

        # Проверяем наличие задачи в Redis
        job_key = f"arq:job:{job_id}"
        job_data = await redis_client.hgetall(job_key)

        if not job_data:
            # Проверяем в завершённых задачах
            result_key = f"arq:result:{job_id}"
            result = await redis_client.get(result_key)
            
            if result:
                import json
                result_data = json.loads(result)
                return {
                    "order_id": order_id,
                    "job_id": job_id,
                    "status": "finished",
                    "result": result_data,
                }
            
            return {
                "order_id": order_id,
                "status": "not_found",
                "message": "Заказ не найден в очереди",
            }

        # Извлекаем статус из данных задачи
        status = job_data.get("status", "unknown")
        
        result = {
            "order_id": order_id,
            "job_id": job_id,
            "status": status,
        }

        # Добавляем время создания, если доступно
        if "created_at" in job_data:
            result["created_at"] = job_data["created_at"]
        if "started_at" in job_data:
            result["started_at"] = job_data["started_at"]
        if "finished_at" in job_data:
            result["finished_at"] = job_data["finished_at"]

        await redis_client.aclose()
        return result

    except Exception as e:
        logger.error(f"Ошибка получения статуса заказа {order_id}: {e}")
        return {
            "order_id": order_id,
            "status": "error",
            "error": str(e),
        }


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "autosupercell"}


@router.get("/proxy/status")
async def proxy_status():
    """
    Статус прокси: включены ли, сколько загружено, есть ли файл.
    Используйте перед покупкой, чтобы убедиться, что прокси будут использоваться.
    """
    from pathlib import Path
    proxy_file = Path(settings.PROXY_LIST_FILE)
    return {
        "proxy_enabled": settings.PROXY_ENABLED,
        "proxies_loaded": len(proxy_manager.proxies),
        "proxy_list_file": settings.PROXY_LIST_FILE,
        "proxy_file_exists": proxy_file.exists(),
        "message": (
            "Прокси не используются: включите PROXY_ENABLED=true в .env и добавьте прокси в "
            f"{settings.PROXY_LIST_FILE} (или настройте Novada)."
            if not settings.PROXY_ENABLED or not proxy_manager.proxies
            else f"Загружено прокси: {len(proxy_manager.proxies)}."
        ),
    }


@router.get("/ai/status")
async def ai_status():
    """
    Статус AI-провайдера (OpenAI / Claude / Gemini).
    Проверьте, что выбранный в AI_PROVIDER провайдер доступен (ключ в .env).
    """
    from app.core.ai_product_search import AIProductSearch
    search = AIProductSearch()
    provider_name = getattr(settings, "AI_PROVIDER", "openai")
    available = search.provider is not None and search.provider.is_available()
    return {
        "provider": provider_name,
        "available": available,
        "message": (
            f"Провайдер {provider_name} доступен."
            if available
            else f"Провайдер {provider_name} недоступен. Проверьте в .env: "
            + (
                "ANTHROPIC_API_KEY для claude"
                if provider_name == "claude"
                else "GEMINI_API_KEY для gemini"
                if provider_name == "gemini"
                else "OPENAI_API_KEY для openai"
            )
        ),
    }


@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    # Здесь будет экспорт метрик Prometheus
    return {"status": "ok"}

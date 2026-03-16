"""
ARQ worker для обработки заказов в фоне.

Задачи:
  process_order_task          — старый flow (OrderProcessor + card_info)
  funpay_purchase_task        — НОВЫЙ flow: email + OTP → POST /supercell/purchase
                                специально для заказов FunPay

Исправления по сравнению с оригиналом:
  - добавлена ветка else (failed) в process_order_task
  - добавлена задача funpay_purchase_task с Redis-lock по email
  - блокировка повторной обработки через Redis SET processed_orders
"""

import asyncio
import time
from typing import Dict, Optional

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from loguru import logger

from app.config import settings
from app.services.order_processor import OrderProcessor
from app.integrations.plati import plati_integration
from app.integrations.kupikod import kupikod_integration
from app.integrations.funpay import funpay_integration
from app.integrations.avito import avito_integration


# ──────────────────────────── вспомогательные ────────────────────────────────

async def _redis_lock(redis, key: str, ttl: int = 700) -> bool:
    """
    Попытаться захватить Redis-блокировку.

    Args:
        redis: клиент Redis (из arq ctx)
        key:   ключ блокировки
        ttl:   время жизни (сек) — чуть больше таймаута покупки 600 сек

    Returns:
        True если блокировка захвачена, False если уже занята
    """
    # SET NX EX — атомарно: записать только если не существует
    result = await redis.set(f"lock:{key}", "1", ex=ttl, nx=True)
    return bool(result)


async def _redis_unlock(redis, key: str) -> None:
    """Снять Redis-блокировку."""
    await redis.delete(f"lock:{key}")


async def _is_order_processed(redis, order_id: str) -> bool:
    """Проверить, обрабатывался ли заказ ранее."""
    return bool(await redis.exists(f"processed_order:{order_id}"))


async def _mark_order_processed(redis, order_id: str, ttl: int = 86400) -> None:
    """Отметить заказ как обработанный (хранить 24 часа)."""
    await redis.set(f"processed_order:{order_id}", "1", ex=ttl)


def _safe_log_order(order_data: Dict) -> Dict:
    """Вернуть копию order_data без чувствительных полей для логирования."""
    safe = {k: v for k, v in order_data.items() if k != "email_password"}
    if "email_password" in order_data:
        safe["email_password"] = "***"
    return safe


# ──────────────────────────── задачи ARQ ─────────────────────────────────────

async def process_order_task(ctx: Dict, order_data: Dict) -> Dict:
    """
    Задача обработки заказа (старый flow — OrderProcessor + card_info).

    Используется для источников: plati, kupikod, avito, manual.
    """
    order_id = order_data.get("order_id", "unknown")
    source = order_data.get("source", "unknown")
    logger.info(f"[ARQ] process_order_task: order_id={order_id}, source={source}")

    processor = OrderProcessor()
    result = await processor.process_order(order_data)

    proof_data = result.get("proof", {})

    if result.get("success"):
        logger.info(f"[ARQ] Заказ {order_id} выполнен успешно")
        if source == "plati":
            await plati_integration.update_order_status(order_id, "completed", proof_data)
        elif source == "kupikod":
            await kupikod_integration.send_proof(order_id, proof_data)
        elif source == "funpay":
            await funpay_integration.update_order_status(order_id, "completed", proof_data)
        elif source == "avito":
            await avito_integration.update_order_status(order_id, "completed", proof_data)
    else:
        # ← ИСПРАВЛЕНО: раньше этой ветки не было!
        error_msg = result.get("error") or result.get("message") or "Неизвестная ошибка"
        logger.error(f"[ARQ] Заказ {order_id} завершён с ошибкой: {error_msg}")
        fail_proof = {"error": error_msg, **proof_data}
        if source == "plati":
            await plati_integration.update_order_status(order_id, "failed", fail_proof)
        elif source == "kupikod":
            # kupikod не имеет update_order_status, шлём что есть
            try:
                await kupikod_integration.update_order_status(order_id, "failed", fail_proof)
            except Exception:
                pass
        elif source == "funpay":
            await funpay_integration.update_order_status(order_id, "failed", fail_proof)
        elif source == "avito":
            await avito_integration.update_order_status(order_id, "failed", fail_proof)

    return result


async def funpay_purchase_task(ctx: Dict, order_data: Dict) -> Dict:
    """
    НОВАЯ задача: покупка через POST /supercell/purchase для заказов FunPay.

    Принимает order_data с полями:
      order_id, email, game, product_name, product_type,
      verification_code (опц.), email_password (опц.)

    Возвращает результат покупки.
    """
    order_id = order_data.get("order_id", "unknown")
    email = order_data.get("email", "")

    logger.info(
        f"[ARQ] funpay_purchase_task: order_id={order_id}, "
        f"email={email}, game={order_data.get('game')}, "
        f"product={order_data.get('product_name')}"
    )

    # Проверяем дублирование
    redis = ctx.get("redis")
    if redis:
        if await _is_order_processed(redis, order_id):
            logger.warning(f"[ARQ] Заказ {order_id} уже был обработан, пропускаем")
            return {"success": False, "error": "already_processed", "order_id": order_id}

    # Redis-lock по email: предотвращаем параллельные сессии для одного email
    email_lock_key = f"email:{email.lower()}"
    lock_acquired = False
    if redis:
        lock_acquired = await _redis_lock(redis, email_lock_key, ttl=700)
        if not lock_acquired:
            logger.warning(
                f"[ARQ] Email {email} уже обрабатывается в другой задаче. "
                f"Заказ {order_id} будет повторён позже."
            )
            # Возвращаем специальный код — автоматический скрипт повторит попытку
            return {"success": False, "error": "email_locked", "order_id": order_id, "retry": True}

    result = {}
    try:
        result = await _call_purchase_api(order_data)

        proof_data = {
            "success": result.get("success"),
            "message": result.get("message", ""),
            "url": result.get("url", ""),
            "screenshot": result.get("screenshot", ""),
            "checkout_screenshot": result.get("checkout_screenshot", ""),
        }

        if result.get("success"):
            logger.info(f"[ARQ] FunPay заказ {order_id} выполнен ✅")
            await funpay_integration.update_order_status(order_id, "completed", proof_data)
            if redis:
                await _mark_order_processed(redis, order_id)
        else:
            error_msg = result.get("error") or result.get("message") or "Ошибка покупки"
            logger.error(f"[ARQ] FunPay заказ {order_id} провалился: {error_msg}")
            await funpay_integration.update_order_status(
                order_id,
                "failed",
                {"error": error_msg, **proof_data},
            )
            if redis:
                await _mark_order_processed(redis, order_id)

    except Exception as exc:
        logger.exception(f"[ARQ] Неожиданная ошибка при обработке заказа {order_id}: {exc}")
        await funpay_integration.update_order_status(
            order_id, "failed", {"error": str(exc)}
        )
        result = {"success": False, "error": str(exc), "order_id": order_id}
        if redis:
            await _mark_order_processed(redis, order_id)

    finally:
        if redis and lock_acquired:
            await _redis_unlock(redis, email_lock_key)

    return result


async def _call_purchase_api(order_data: Dict) -> Dict:
    """
    Вызвать POST /supercell/purchase через внутренний HTTP.

    Использует тот же API_URL и API_KEY что и purchase_demo.py,
    но работает асинхронно внутри арq-воркера.
    """
    import os

    api_url = os.environ.get("AUTOSUPERCELL_API_URL", "http://localhost:8000/api/v1")
    api_key = os.environ.get("AUTOSUPERCELL_API_KEY", "")

    payload = {
        "email": order_data["email"],
        "game": order_data.get("game", "brawl-stars"),
        "product_name": order_data.get("product_name", "80 Gems"),
        "product_type": order_data.get("product_type", "gems"),
    }

    verification_code = order_data.get("verification_code")
    email_password = order_data.get("email_password")

    if verification_code:
        payload["verification_code"] = verification_code
    if email_password:
        payload["email_password"] = email_password

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    logger.info(f"[ARQ] Вызов POST {api_url}/supercell/purchase для {order_data.get('email')}")

    async with httpx.AsyncClient(timeout=620) as client:
        resp = await client.post(
            f"{api_url}/supercell/purchase",
            json=payload,
            headers=headers,
        )

    if resp.status_code == 200:
        return resp.json()
    else:
        try:
            err = resp.json()
        except Exception:
            err = {"detail": resp.text[:300]}
        error_detail = err.get("detail") or err.get("error") or f"HTTP {resp.status_code}"
        return {"success": False, "error": str(error_detail)}


# ──────────────────────────── настройки воркера ──────────────────────────────

class WorkerSettings:
    """Настройки ARQ worker."""

    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        database=settings.REDIS_DB,
    )

    functions = [
        process_order_task,
        funpay_purchase_task,   # ← НОВАЯ задача
    ]

    max_jobs = 10
    job_timeout = 660  # 11 минут (чуть больше таймаута покупки 600 сек)

    # Контекст передаётся в каждую задачу через ctx["redis"]
    async def on_startup(ctx):
        pass

    async def on_shutdown(ctx):
        pass


# WorkerSettings используется для запуска через arq CLI:
# arq app.workers.arq_worker.WorkerSettings
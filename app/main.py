"""Главный файл приложения FastAPI."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_client import make_asgi_app

from app.api.routes import router
from app.config import settings

# ─── Логирование ────────────────────────────────────────────────────────────
logger.add(
    settings.LOG_FILE,
    rotation="10 MB",
    retention="7 days",
    level=settings.LOG_LEVEL,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

# Отдельный файл только для действий автоматизации (клики, навигация, шаги оплаты)
def _automation_filter(record):
    return record["extra"].get("automation") is True

logger.add(
    settings.LOG_AUTOMATION_FILE,
    rotation="5 MB",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    filter=_automation_filter,
)

# ─── Эндпоинты, которые не требуют API-ключа ────────────────────────────────
_PUBLIC_PATHS = {
    "/",
    "/api/v1/health",
    "/api/v1/routes",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
}


# ─── Lifespan (заменяет устаревшие @app.on_event) ───────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при запуске и очистка при остановке."""
    logger.info("Запуск AutoSupercell сервиса...")
    yield
    logger.info("Остановка AutoSupercell сервиса...")


# ─── Приложение ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="AutoSupercell",
    description="Автоматизированный сервис для покупки товаров в Supercell Store",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── CORS middleware ──────────────────────────────────────────────────────────
# Читаем список допустимых origins из настроек.
# В продакшене задайте в .env: CORS_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
_raw_origins = settings.CORS_ORIGINS.strip()
if _raw_origins == "*":
    _allow_origins = ["*"]
else:
    _allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_origins != ["*"],  # credentials несовместимы с wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── API-Key middleware ───────────────────────────────────────────────────────
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """
    Проверка API-ключа (заголовок X-API-Key).

    Активируется только если в .env задан API_SECRET_KEY.
    Публичные пути (/, /api/v1/health, /docs, /metrics ...) пропускаются без ключа.
    """
    if settings.API_SECRET_KEY:
        # Пропускаем публичные пути и OPTIONS preflight
        if request.method != "OPTIONS" and request.url.path not in _PUBLIC_PATHS:
            provided = request.headers.get("X-API-Key", "")
            if provided != settings.API_SECRET_KEY:
                logger.warning(
                    "Отклонён запрос без/с неверным API-ключом: %s %s",
                    request.method,
                    request.url.path,
                )
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": (
                            "Неверный или отсутствующий API-ключ. "
                            "Передайте заголовок X-API-Key."
                        )
                    },
                )
    return await call_next(request)


# ─── Роуты ───────────────────────────────────────────────────────────────────
from app.api.auth_routes import router as auth_router
from app.api.supercell_auth_routes import router as supercell_auth_router

app.include_router(router, prefix="/api/v1", tags=["orders"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["authentication"])
app.include_router(supercell_auth_router, prefix="/api/v1", tags=["supercell"])

# Store routes (покупка товаров)
try:
    from app.api.store_routes import router as store_router

    app.include_router(store_router, prefix="/api/v1", tags=["store"])
    logger.info("Store routes подключены успешно")
except Exception as e:
    import traceback

    logger.error("Ошибка подключения store routes: %s\n%s", e, traceback.format_exc())


# ─── Prometheus metrics ───────────────────────────────────────────────────────
if settings.PROMETHEUS_ENABLED:
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)


# ─── Базовые эндпоинты ────────────────────────────────────────────────────────
@app.get("/")
async def root():
    """Корневой endpoint."""
    return {
        "service": "AutoSupercell",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/api/v1/routes")
async def list_routes():
    """Список всех доступных endpoints."""
    routes = []
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            routes.append(
                {
                    "path": route.path,
                    "methods": list(route.methods),
                }
            )
    return {"routes": routes}


@app.get("/api/v1/ai/status")
async def ai_status():
    """
    Статус AI-провайдера (OpenAI / Claude / Gemini).

    Проверка: в .env заданы AI_PROVIDER и соответствующий API-ключ.
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
            else (
                f"Провайдер {provider_name} недоступен. В .env проверьте: "
                + (
                    "ANTHROPIC_API_KEY для claude"
                    if provider_name == "claude"
                    else (
                        "GEMINI_API_KEY для gemini"
                        if provider_name == "gemini"
                        else "OPENAI_API_KEY для openai"
                    )
                )
            )
        ),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )

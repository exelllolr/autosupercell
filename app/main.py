"""Главный файл приложения FastAPI."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from prometheus_client import make_asgi_app
from app.config import settings
from app.api.routes import router

# Настройка логирования
logger.add(
    settings.LOG_FILE,
    rotation="10 MB",
    retention="7 days",
    level=settings.LOG_LEVEL,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

app = FastAPI(
    title="AutoSupercell",
    description="Автоматизированный сервис для покупки товаров в Supercell Store",
    version="0.1.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем routes
from app.api.auth_routes import router as auth_router
from app.api.supercell_auth_routes import router as supercell_auth_router

app.include_router(router, prefix="/api/v1", tags=["orders"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["authentication"])
app.include_router(supercell_auth_router, prefix="/api/v1", tags=["supercell"])

# Подключаем store routes (покупка товаров)
try:
    from app.api.store_routes import router as store_router
    app.include_router(store_router, prefix="/api/v1", tags=["store"])
    logger.info("Store routes подключены успешно")
except Exception as e:
    import traceback
    error_msg = f"Ошибка подключения store routes: {e}\n{traceback.format_exc()}"
    logger.error(error_msg)
    logger.error(error_msg)


@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске."""
    logger.info("Запуск AutoSupercell сервиса...")


@app.on_event("shutdown")
async def shutdown_event():
    """Очистка при остановке."""
    logger.info("Остановка AutoSupercell сервиса...")


# Prometheus metrics
if settings.PROMETHEUS_ENABLED:
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)


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
            routes.append({
                "path": route.path,
                "methods": list(route.methods),
            })
    return {"routes": routes}


@app.get("/api/v1/ai/status")
async def ai_status():
    """
    Статус AI-провайдера (OpenAI / Claude / Gemini).
    Проверка: в .env заданы AI_PROVIDER и соответствующий API ключ.
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
            else f"Провайдер {provider_name} недоступен. В .env проверьте: "
            + (
                "ANTHROPIC_API_KEY для claude"
                if provider_name == "claude"
                else "GEMINI_API_KEY для gemini"
                if provider_name == "gemini"
                else "OPENAI_API_KEY для openai"
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

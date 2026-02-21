"""
Запуск API-сервера с корректной настройкой event loop на Windows.

На Windows Patchright/Playwright требует ProactorEventLoop (для create_subprocess_exec).
Uvicorn при старте выставляет WindowsSelectorEventLoopPolicy, из-за чего возникает
NotImplementedError при запуске браузера. Этот скрипт выставляет политику и патчит
uvicorn до его запуска, затем запускает uvicorn.

Использование:
  python run_server.py

Или с параметрами (host/port из .env или по умолчанию):
  python run_server.py --host 0.0.0.0 --port 8000
"""
import sys
import asyncio


def _setup_windows_event_loop():
    if sys.platform != "win32":
        return
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    # Патчим uvicorn, чтобы при вызове setup_event_loop() (в т.ч. в воркерах) не подменяли на Selector
    import uvicorn.loops.asyncio as _uva
    _orig = _uva.asyncio_setup

    def _patched(use_subprocess: bool = False) -> None:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    _uva.asyncio_setup = _patched


if __name__ == "__main__":
    _setup_windows_event_loop()

    import uvicorn
    from app.config import settings

    uvicorn.run(
        "app.main:app",
        host=getattr(settings, "HOST", "0.0.0.0"),
        port=getattr(settings, "PORT", 8000),
        reload=getattr(settings, "DEBUG", False),
    )

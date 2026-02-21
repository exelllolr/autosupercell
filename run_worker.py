#!/usr/bin/env python
"""Скрипт запуска ARQ worker."""

import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    # Запуск через arq CLI
    import subprocess
    
    print("Запуск ARQ worker...")
    print("Используйте команду: arq app.workers.arq_worker.WorkerSettings")
    print("Или через Docker Compose: docker-compose up worker")
    
    # Альтернативный способ запуска напрямую
    try:
        from arq.worker import Worker
        from app.workers.arq_worker import WorkerSettings
        import asyncio
        from loguru import logger
        
        async def run_worker():
            logger.info("Запуск ARQ worker...")
            worker = Worker(
                functions=WorkerSettings.functions,
                redis_settings=WorkerSettings.redis_settings,
                max_jobs=WorkerSettings.max_jobs,
                job_timeout=WorkerSettings.job_timeout,
            )
            logger.info("Worker запущен, ожидание задач...")
            await worker.async_run()
        
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        print("\nОстановка worker...")
    except Exception as e:
        print(f"Ошибка: {e}")
        sys.exit(1)

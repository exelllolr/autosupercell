.PHONY: help install test run-api run-worker docker-up docker-down docker-logs clean

help:
	@echo "Доступные команды:"
	@echo "  make install      - Установить зависимости"
	@echo "  make test         - Запустить тесты"
	@echo "  make run-api      - Запустить API сервер"
	@echo "  make run-worker   - Запустить worker"
	@echo "  make docker-up    - Запустить через Docker Compose"
	@echo "  make docker-down  - Остановить Docker Compose"
	@echo "  make docker-logs  - Показать логи Docker"
	@echo "  make clean        - Очистить временные файлы"

install:
	pip install -r requirements.txt
	playwright install chromium
	playwright install-deps chromium

test:
	pytest tests/ -v

run-api:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-worker:
	python run_worker.py

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

clean:
	find . -type d -name __pycache__ -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name ".pytest_cache" -exec rm -r {} +
	find . -type d -name ".coverage" -exec rm -r {} +

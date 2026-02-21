"""Prometheus метрики для мониторинга."""

from prometheus_client import Counter, Histogram, Gauge
from typing import Optional

# Инициализация метрик при импорте модуля

# Метрики заказов
orders_total = Counter(
    "autosupercell_orders_total",
    "Total number of orders processed",
    ["status", "source"],
)

order_processing_time = Histogram(
    "autosupercell_order_processing_seconds",
    "Time spent processing orders",
    ["status"],
    buckets=[30, 60, 120, 180, 300, 600],
)

orders_in_queue = Gauge(
    "autosupercell_orders_in_queue",
    "Number of orders currently in queue",
)

# Метрики браузера
browser_sessions_total = Counter(
    "autosupercell_browser_sessions_total",
    "Total number of browser sessions",
    ["status"],
)

# Метрики платежей
payments_total = Counter(
    "autosupercell_payments_total",
    "Total number of payments",
    ["status", "method"],
)

payment_processing_time = Histogram(
    "autosupercell_payment_processing_seconds",
    "Time spent processing payments",
    ["method"],
)

# Метрики AI поиска
ai_searches_total = Counter(
    "autosupercell_ai_searches_total",
    "Total number of AI product searches",
    ["status"],
)

ai_search_time = Histogram(
    "autosupercell_ai_search_seconds",
    "Time spent on AI product search",
)

# Метрики прокси
proxy_rotations_total = Counter(
    "autosupercell_proxy_rotations_total",
    "Total number of proxy rotations",
)

proxy_failures_total = Counter(
    "autosupercell_proxy_failures_total",
    "Total number of proxy failures",
)

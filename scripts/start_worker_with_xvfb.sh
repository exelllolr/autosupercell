#!/bin/bash
# scripts/start_worker_with_xvfb.sh — запуск ARQ worker с виртуальным дисплеем Xvfb.
#
# Worker обрабатывает заказы (OrderProcessor) с браузерной автоматизацией.
# Chrome в headed режиме (BROWSER_HEADLESS=false) требует DISPLAY.
# Без Xvfb DISPLAY=:99 не существует — Chrome падает или принудительно headless.
#
# Использование (в docker-compose для worker):
#   command: /app/scripts/start_worker_with_xvfb.sh
#
# Вручную:
#   chmod +x scripts/start_worker_with_xvfb.sh && ./scripts/start_worker_with_xvfb.sh

set -e

DISPLAY_NUM="${DISPLAY_NUM:-99}"
DISPLAY_WIDTH="${DISPLAY_WIDTH:-1920}"
DISPLAY_HEIGHT="${DISPLAY_HEIGHT:-1080}"
XVFB_DEPTH="${XVFB_DEPTH:-24}"

DISPLAY_VAL=":${DISPLAY_NUM}"

echo "========================================================"
echo "  AutoSupercell Worker — запуск с Xvfb"
echo "========================================================"
echo "  DISPLAY      = ${DISPLAY_VAL}"
echo "  Разрешение   = ${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x${XVFB_DEPTH}"
echo ""

if ! command -v Xvfb &> /dev/null; then
    echo "[WARN] Xvfb не найден. Запускаем worker без виртуального дисплея (headless)."
    echo "       Для установки: apt-get install -y xvfb"
    echo ""
    exec arq app.workers.arq_worker.WorkerSettings
fi

echo "[INFO] Запуск Xvfb на ${DISPLAY_VAL}..."
Xvfb "${DISPLAY_VAL}" \
    -screen 0 "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x${XVFB_DEPTH}" \
    -ac \
    +extension GLX \
    +render \
    -noreset \
    &> /tmp/xvfb_worker.log &

XVFB_PID=$!

MAX_WAIT="${XVFB_MAX_WAIT:-20}"
for i in $(seq 1 $MAX_WAIT); do
    if xdpyinfo -display "${DISPLAY_VAL}" &>/dev/null 2>&1; then
        echo "[INFO] Xvfb готов (PID=${XVFB_PID}, ждали ${i} сек)"
        break
    fi
    if [ $i -eq $MAX_WAIT ]; then
        echo "[WARN] Xvfb не ответил за ${MAX_WAIT} сек — проверьте /tmp/xvfb_worker.log"
    fi
    sleep 1
done

export DISPLAY="${DISPLAY_VAL}"
echo "[INFO] DISPLAY=${DISPLAY} экспортирован"
echo ""

cleanup() {
    echo "[INFO] Остановка Xvfb (PID=${XVFB_PID})..."
    kill "${XVFB_PID}" 2>/dev/null || true
    wait "${XVFB_PID}" 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT EXIT

echo "[INFO] Запуск ARQ worker..."
exec arq app.workers.arq_worker.WorkerSettings

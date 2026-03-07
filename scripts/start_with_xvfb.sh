#!/bin/bash
# scripts/start_with_xvfb.sh — запуск AutoSupercell API с виртуальным дисплеем Xvfb.
#
# Зачем нужен Xvfb:
#   Cloudflare Turnstile (встроен в форму логина Supercell ID) блокирует headless Chrome —
#   форма входа не рендерится и email-поле не появляется в DOM.
#   Xvfb создаёт виртуальный X11-дисплей: Chrome запускается в "headed" режиме
#   (BROWSER_HEADLESS=false), но реального монитора не нужно.
#   Для Turnstile это неотличимо от настоящего браузера — форма рендерится, вход проходит.
#
# Использование (автоматически через Docker CMD):
#   docker compose up -d --build
#
# Вручную:
#   chmod +x scripts/start_with_xvfb.sh && ./scripts/start_with_xvfb.sh
#
# Переменные окружения:
#   DISPLAY_NUM     — номер виртуального дисплея (по умолчанию 99 → DISPLAY=:99)
#   DISPLAY_WIDTH   — ширина виртуального дисплея (по умолчанию 1920)
#   DISPLAY_HEIGHT  — высота виртуального дисплея (по умолчанию 1080)
#   XVFB_DEPTH      — глубина цвета (по умолчанию 24)

set -e

DISPLAY_NUM="${DISPLAY_NUM:-99}"
DISPLAY_WIDTH="${DISPLAY_WIDTH:-1920}"
DISPLAY_HEIGHT="${DISPLAY_HEIGHT:-1080}"
XVFB_DEPTH="${XVFB_DEPTH:-24}"

DISPLAY_VAL=":${DISPLAY_NUM}"

echo "========================================================"
echo "  AutoSupercell — запуск с виртуальным дисплеем Xvfb"
echo "========================================================"
echo "  DISPLAY      = ${DISPLAY_VAL}"
echo "  Разрешение   = ${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x${XVFB_DEPTH}"
echo ""

# ── Проверяем, установлен ли Xvfb ────────────────────────────────────────────
if ! command -v Xvfb &> /dev/null; then
    echo "[WARN] Xvfb не найден. Запускаем без виртуального дисплея (headless режим)."
    echo "       Для установки: apt-get install -y xvfb"
    echo ""
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
fi

# ── Запускаем Xvfb ────────────────────────────────────────────────────────────
echo "[INFO] Запуск Xvfb на ${DISPLAY_VAL}..."

# Флаги:
#   -screen 0 WxHxD  — разрешение и глубина цвета
#   -ac              — отключить контроль доступа (для работы внутри контейнера)
#   +extension GLX   — включить OpenGL (нужен для Chrome)
#   +render          — включить Render-расширение
#   -noreset         — не сбрасывать дисплей при выходе последнего клиента
Xvfb "${DISPLAY_VAL}" \
    -screen 0 "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x${XVFB_DEPTH}" \
    -ac \
    +extension GLX \
    +render \
    -noreset \
    &> /tmp/xvfb.log &

XVFB_PID=$!

# ── Ждём готовности Xvfb ─────────────────────────────────────────────────────
MAX_WAIT=10
for i in $(seq 1 $MAX_WAIT); do
    if xdpyinfo -display "${DISPLAY_VAL}" &>/dev/null 2>&1; then
        echo "[INFO] Xvfb готов (PID=${XVFB_PID}, ждали ${i} сек)"
        break
    fi
    if [ $i -eq $MAX_WAIT ]; then
        echo "[WARN] Xvfb не ответил за ${MAX_WAIT} сек — проверьте /tmp/xvfb.log"
        echo "       Продолжаем запуск (Chrome сам обработает отсутствие дисплея)."
    fi
    sleep 1
done

# ── Экспортируем переменную DISPLAY ───────────────────────────────────────────
export DISPLAY="${DISPLAY_VAL}"
echo "[INFO] DISPLAY=${DISPLAY} экспортирован"
echo ""

# ── Graceful shutdown: при SIGTERM/SIGINT останавливаем Xvfb ─────────────────
cleanup() {
    echo "[INFO] Получен сигнал завершения, останавливаем Xvfb (PID=${XVFB_PID})..."
    kill "${XVFB_PID}" 2>/dev/null || true
    wait "${XVFB_PID}" 2>/dev/null || true
    echo "[INFO] Xvfb остановлен."
}
trap cleanup SIGTERM SIGINT EXIT

# ── Запускаем API ─────────────────────────────────────────────────────────────
echo "[INFO] Запуск AutoSupercell API (uvicorn)..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --loop asyncio

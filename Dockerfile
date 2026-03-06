# Using Debian Bookworm (stable) for better package compatibility
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies:
#   - Chromium/Chrome runtime libs (Patchright/Playwright)
#   - libgl1          → required by opencv-python (cv2 imports libGL.so.1)
#   - libglib2.0-0    → required by opencv-python (libgthread-2.0.so.0)
#   - libxext6        → required by Chrome (libXext.so.6)
#   - fonts-unifont   → replaces ttf-unifont (unavailable in Bookworm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    fonts-unifont \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    libxshmfence1 \
    libxss1 \
    libpangocairo-1.0-0 \
    libcairo-gobject2 \
    libgdk-pixbuf-xlib-2.0-0 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (Docker layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Patchright browsers.
# chromium — основной браузер; chrome — для BROWSER_USE_CHROME=true.
# Запускается отдельным слоем, чтобы не пересобирать при изменении кода.
RUN patchright install chromium && patchright install chrome

# Copy application code
COPY . .

# Create runtime directories (также создаются при монтировании volumes,
# но лучше иметь их в образе для случаев без volume-mount)
RUN mkdir -p logs screenshots proofs videos

# Only the API port is exposed.
# Port 9090 removed: Prometheus metrics are served at 8000/metrics, not a separate port.
EXPOSE 8000

# Health check.
# start_period=60s: первый запуск с установкой/прогревом Chrome может занять до 60 сек.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

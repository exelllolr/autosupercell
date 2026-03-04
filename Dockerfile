# Using Debian Bookworm (stable) instead of Trixie for better package compatibility
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies including Playwright browser dependencies
RUN apt-get update && apt-get install -y \
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
    # Additional dependencies for Chromium
    libxshmfence1 \
    libxss1 \
    libpangocairo-1.0-0 \
    libcairo-gobject2 \
    libgdk-pixbuf-xlib-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Patchright browsers (Chromium + Chrome for BROWSER_USE_CHROME=true)
RUN patchright install chromium && patchright install chrome

# Note: patchright uses same deps as Playwright; we install system deps manually above
# This avoids issues with unavailable font packages (ttf-ubuntu-font-family, ttf-unifont)
# in newer Debian versions. We use fonts-unifont instead of ttf-unifont.

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs screenshots proofs

# Expose ports
EXPOSE 8000 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

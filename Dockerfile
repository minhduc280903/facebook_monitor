# Sử dụng một base image Python nhẹ
FROM python:3.11-slim

# 🌍 FIX ENCODING: Set UTF-8 locale
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1

# Thiết lập thư mục làm việc bên trong container
WORKDIR /app

# Cài đặt system dependencies cần thiết cho psycopg2 và Playwright
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    locales \
    fonts-unifont \
    fonts-liberation \
    libgobject-2.0-0 \
    libglib2.0-0 \
    libnss3 \
    libnss3-dev \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libgio-2.0-0 \
    libdrm2 \
    libexpat1 \
    libxcb1 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/* \
    && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen \
    && locale-gen en_US.UTF-8

# Cài đặt các dependencies trước để tận dụng Docker layer caching
# Copy unified requirements file (Phase 3.2: consolidated all dependencies into one file)
COPY requirements.txt .
# Increase timeout to 300s for slow networks
RUN pip install --no-cache-dir --timeout=300 -r requirements.txt

# Download browser binaries for Playwright
# NOTE: Using chromium only (deps already installed via apt-get above)
RUN playwright install chromium

# Copy toàn bộ code của dự án vào container
COPY . .

# Copy auto_login.py và account.txt nếu có
COPY auto_login.py* /app/
COPY account.txt* /app/

# Tạo thư mục logs và sessions nếu chưa tồn tại
RUN mkdir -p logs sessions

# Expose port mà FastAPI sẽ chạy
EXPOSE 8000

# Health check để đảm bảo API hoạt động
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Lệnh để chạy ứng dụng khi container khởi động
# Cleanup session locks trước khi chạy service
CMD sh -c 'find ./sessions -name "SingletonLock" -type f -delete 2>/dev/null || true; \
           find ./sessions -name "SingletonCookie" -type f -delete 2>/dev/null || true; \
           find ./sessions -name "SingletonSocket" -type f -delete 2>/dev/null || true; \
           echo "✅ Session locks cleaned"; \
           exec "$@"' -- uvicorn api.main:app --host 0.0.0.0 --port 8000

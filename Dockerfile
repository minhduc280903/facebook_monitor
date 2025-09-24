# Sử dụng một base image Python nhẹ
FROM python:3.11-slim

# Thiết lập thư mục làm việc bên trong container
WORKDIR /app

# Cài đặt system dependencies cần thiết cho psycopg2 và các packages khác
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt các dependencies trước để tận dụng Docker layer caching
# Copy file requirements của backend và webapp và cài đặt
COPY backend_requirements.txt .
COPY webapp_streamlit/requirements.txt ./webapp_requirements.txt
RUN pip install --no-cache-dir -r backend_requirements.txt
RUN pip install --no-cache-dir -r webapp_requirements.txt

# Download browser binaries for Playwright
RUN playwright install --with-deps chromium

# Copy toàn bộ code của dự án vào container
COPY . .

# Tạo thư mục logs nếu chưa tồn tại
RUN mkdir -p logs

# Expose port mà FastAPI sẽ chạy
EXPOSE 8000

# Health check để đảm bảo API hoạt động
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Lệnh để chạy ứng dụng khi container khởi động
# Chạy uvicorn, trỏ đến app object trong file api/main.py
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

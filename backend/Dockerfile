# ==============================================================================
# Dockerfile cho dịch vụ Backend (FastAPI + SQLAlchemy + SQLite)
# TTCS K18C4 - Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản
# ==============================================================================

FROM python:3.11-slim

# Thiết lập các biến môi trường mặc định của Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Thư mục làm việc trong container
WORKDIR /app

# Cài đặt curl phục vụ kiểm tra sức khỏe container (HEALTHCHECK)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt thư viện phụ thuộc
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn backend vào container
COPY . .

# Tạo thư mục dữ liệu cho volume SQLite
RUN mkdir -p /app/data

# Mở cổng 8000 cho FastAPI
EXPOSE 8000

# Kiểm tra định kỳ trạng thái endpoint health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Lệnh khởi chạy uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

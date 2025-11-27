FROM python:3.11-slim

# Установка grpc_health_probe
RUN apt-get update && \
    apt-get install -y wget && \
    wget -qO/bin/grpc_health_probe https://github.com/grpc-ecosystem/grpc-health-probe/releases/download/v0.4.24/grpc_health_probe-linux-amd64 && \
    chmod +x /bin/grpc_health_probe && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Создание non-root пользователя
RUN useradd -m -u 1000 appuser

# Рабочая директория
WORKDIR /app

# Копирование requirements и установка зависимостей
COPY services/review-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование proto файлов и генерация Python кода
COPY proto/ ./proto/
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/reviews.proto

# Копирование исходного кода
COPY services/review-service/server.py .

# Смена владельца файлов
RUN chown -R appuser:appuser /app

# Переключение на non-root пользователя
USER appuser

# Порты
EXPOSE 50051 8080

# Запуск сервиса
CMD ["python", "server.py"]

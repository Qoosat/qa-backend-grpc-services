#!/bin/bash
# Скрипт для генерации Python кода из proto файлов

python -m grpc_tools.protoc \
    -I../../proto \
    --python_out=. \
    --grpc_python_out=. \
    ../../proto/reviews.proto

echo "Proto files generated successfully"

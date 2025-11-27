#!/bin/bash
# Скрипт для сборки и отправки Docker образов

set -e

echo "==================================="
echo "Building Docker images..."
echo "==================================="

# Build Review Service
echo ""
echo "Building Review Service..."
docker build -t nklrif/review-service:latest -f services/review-service/Dockerfile .

# Build Moderation Service
echo ""
echo "Building Moderation Service..."
docker build -t nklrif/moderation-service:latest -f services/moderation-service/Dockerfile .

echo ""
echo "==================================="
echo "Docker images built successfully!"
echo "==================================="
docker images | grep nklrif

echo ""
echo "==================================="
echo "Pushing to Docker Hub..."
echo "==================================="

# Push Review Service
echo ""
echo "Pushing Review Service..."
docker push nklrif/review-service:latest

# Push Moderation Service
echo ""
echo "Pushing Moderation Service..."
docker push nklrif/moderation-service:latest

echo ""
echo "==================================="
echo "✅ All images pushed successfully!"
echo "==================================="
echo ""
echo "Images available at:"
echo "  - https://hub.docker.com/r/nklrif/review-service"
echo "  - https://hub.docker.com/r/nklrif/moderation-service"
echo ""
echo "You can now deploy to Kubernetes:"
echo "  kubectl apply -f k8s/"

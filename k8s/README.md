# Kubernetes Deployment

Манифесты для развертывания Review Service и Moderation Service в Kubernetes.

## Namespace
**dev** - все ресурсы развертываются в этом namespace.

## Файлы

### namespace.yaml
Создание namespace `dev`.

### secret-example.yaml
Пример Secret с DATABASE_URL_POSTGRES. **НЕ КОММИТИТЬ в git!** Создайте свой Secret с реальными credentials:
```bash
kubectl create secret generic qa-secret \
  --from-literal=DATABASE_URL_POSTGRES='postgresql://user:pass@host:5432/db' \
  -n dev
```

### configmap.yaml
ConfigMap с общими настройками (опционально, настройки также прописаны в Deployment).

### review-service-deployment.yaml
- **Deployment**: 2 реплики, стратегия Recreate
- **Service**: ClusterIP, порты 50051 (gRPC), 8080 (health)
- **Resources**: requests 100m/128Mi, limits 200m/256Mi
- **Probes**: liveness/readiness через grpc_health_probe

### moderation-service-deployment.yaml
- **Deployment**: 2 реплики, стратегия Recreate
- **Service**: ClusterIP, порты 50052 (gRPC), 8081 (health)
- **Resources**: requests 100m/128Mi, limits 200m/256Mi
- **Probes**: liveness/readiness через grpc_health_probe

## Применение

### 1. Создать namespace
```bash
kubectl apply -f k8s/namespace.yaml
```

### 2. Создать Secret
```bash
kubectl apply -f k8s/secret-example.yaml
# ИЛИ создать вручную с реальными credentials
```

### 3. Создать ConfigMap (опционально)
```bash
kubectl apply -f k8s/configmap.yaml
```

### 4. Деплой сервисов
```bash
kubectl apply -f k8s/review-service-deployment.yaml
kubectl apply -f k8s/moderation-service-deployment.yaml
```

### 5. Проверка
```bash
kubectl get pods -n dev
kubectl get svc -n dev
kubectl logs -f deployment/review-service -n dev
kubectl logs -f deployment/moderation-service -n dev
```

## Порт-форвардинг для тестирования

### Review Service
```bash
kubectl port-forward svc/review-service 50051:50051 -n dev
```

### Moderation Service
```bash
kubectl port-forward svc/moderation-service 50052:50052 -n dev
```

## Удаление
```bash
kubectl delete -f k8s/moderation-service-deployment.yaml
kubectl delete -f k8s/review-service-deployment.yaml
kubectl delete -f k8s/configmap.yaml
kubectl delete -f k8s/secret-example.yaml
kubectl delete -f k8s/namespace.yaml
```

## Health Checks
Оба сервиса используют `grpc_health_probe` для liveness и readiness проверок:
- Review Service: `grpc_health_probe -addr=:50051`
- Moderation Service: `grpc_health_probe -addr=:50052`

## Environment Variables

### Review Service
- `DATABASE_URL_POSTGRES` - из Secret `qa-secret`
- `MODERATION_SERVICE_HOST=moderation-service`
- `MODERATION_SERVICE_PORT=50052`

### Moderation Service
- `DATABASE_URL_POSTGRES` - из Secret `qa-secret`
- `REVIEW_SERVICE_HOST=review-service`
- `REVIEW_SERVICE_PORT=50051`
- `PROFANITY_WORDS` - список запрещенных слов

## Networking

### ClusterIP (по умолчанию)
Оба сервиса используют **ClusterIP** и доступны только внутри кластера:
- `review-service.dev.svc.cluster.local:50051`
- `moderation-service.dev.svc.cluster.local:50052`

### LoadBalancer (для облачных кластеров)
Для доступа снаружи кластера в облаке (AWS, GCP, Azure):
```bash
kubectl apply -f k8s/loadbalancer.yaml

# Получить внешний IP
kubectl get svc -n dev
# EXTERNAL-IP будет назначен облачным провайдером
```

Подключение через LoadBalancer:
```bash
# Review Service
grpcurl -plaintext <EXTERNAL-IP>:50051 list

# Moderation Service
grpcurl -plaintext <EXTERNAL-IP>:50052 list
```

### NodePort (для локальных кластеров)
Для minikube, kind, k3s и других локальных кластеров:
```bash
kubectl apply -f k8s/nodeport.yaml

# Получить NodePort
kubectl get svc -n dev
```

Подключение через NodePort:
```bash
# Для minikube
minikube service review-service-nodeport -n dev --url
minikube service moderation-service-nodeport -n dev --url

# Для других кластеров
# Review Service: <NODE-IP>:30051
# Moderation Service: <NODE-IP>:30052
grpcurl -plaintext localhost:30051 list
grpcurl -plaintext localhost:30052 list
```

### Ingress (для HTTP/2 gRPC)
Для использования доменных имён и TLS:

**Требования:**
- NGINX Ingress Controller с поддержкой gRPC
- DNS записи для `review.cinescope.local` и `moderation.cinescope.local`

**Установка NGINX Ingress:**
```bash
# Helm
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace

# Или kubectl
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.9.4/deploy/static/provider/cloud/deploy.yaml
```

**Применение Ingress:**
```bash
kubectl apply -f k8s/ingress.yaml
```

**Добавить в /etc/hosts (или C:\Windows\System32\drivers\etc\hosts):**
```
<INGRESS-IP> review.cinescope.local
<INGRESS-IP> moderation.cinescope.local
```

**Подключение через Ingress:**
```bash
# Review Service
grpcurl -plaintext review.cinescope.local:80 list

# Moderation Service
grpcurl -plaintext moderation.cinescope.local:80 list

# С TLS (если настроен)
grpcurl review.cinescope.local:443 list
grpcurl moderation.cinescope.local:443 list
```

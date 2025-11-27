# gRPC Moderation Services для Cinescope

Система автоматической модерации отзывов на фильмы для обучения QA тестированию gRPC API.

## Архитектура

### Review Service (порт 50051)
CRUD операции с отзывами на фильмы:
- `CreateReview` - создать отзыв (сохраняется с hidden=true, затем модерация)
- `GetReview` - получить отзыв по ключу (user_id, movie_id)
- `ListReviews` - список отзывов с фильтрацией и пагинацией
- `UpdateReviewVisibility` - обновить видимость (вызывается из Moderation Service)

### Moderation Service (порт 50052)
Автоматическая модерация отзывов:
- `ModerateReview` - проверить текст на запрещенные слова
- `GetModerationHistory` - история модераций для отзыва
- `GetModerationStats` - статистика модерации

## Workflow
```
1. QA → CreateReview() → Review Service
2. Review Service сохраняет в БД (hidden=true)
3. Review Service → ModerateReview() → Moderation Service
4. Moderation Service проверяет текст
5. Moderation Service → UpdateReviewVisibility() → Review Service
6. Review Service обновляет hidden в БД
7. Moderation Service записывает в moderation_log
8. Response → QA
```

## Быстрый старт

### Локальная разработка

#### 1. Генерация proto файлов
```bash
# Review Service
cd services/review-service
bash generate_proto.sh

# Moderation Service
cd services/moderation-service
bash generate_proto.sh
```

#### 2. Запуск сервисов
```bash
# Terminal 1 - Review Service
cd services/review-service
pip install -r requirements.txt
python server.py

# Terminal 2 - Moderation Service
cd services/moderation-service
pip install -r requirements.txt
python server.py
```

### Docker

#### Build
```bash
# Review Service
docker build -t nklrif/review-service:latest -f services/review-service/Dockerfile .

# Moderation Service
docker build -t nklrif/moderation-service:latest -f services/moderation-service/Dockerfile .
```

#### Run
```bash
# Review Service
docker run -p 50051:50051 --env-file services/review-service/.env nklrif/review-service:latest

# Moderation Service
docker run -p 50052:50052 --env-file services/moderation-service/.env nklrif/moderation-service:latest
```

### Kubernetes

```bash
# Применить все манифесты
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secret-example.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/review-service-deployment.yaml
kubectl apply -f k8s/moderation-service-deployment.yaml

# Проверка
kubectl get pods -n dev
kubectl get svc -n dev

# Port-forward для тестирования
kubectl port-forward svc/review-service 50051:50051 -n dev
kubectl port-forward svc/moderation-service 50052:50052 -n dev
```

---

# Тестовые сценарии с grpcurl

## Установка grpcurl
```bash
# macOS
brew install grpcurl

# Linux
wget https://github.com/fullstorydev/grpcurl/releases/download/v1.8.9/grpcurl_1.8.9_linux_x86_64.tar.gz
tar -xvf grpcurl_1.8.9_linux_x86_64.tar.gz
sudo mv grpcurl /usr/local/bin/

# Windows (через scoop)
scoop install grpcurl
```

## Список доступных методов

### Review Service
```bash
grpcurl -plaintext localhost:50051 list
grpcurl -plaintext localhost:50051 list cinescope.reviews.ReviewService
grpcurl -plaintext localhost:50051 describe cinescope.reviews.ReviewService.CreateReview
```

### Moderation Service
```bash
grpcurl -plaintext localhost:50052 list
grpcurl -plaintext localhost:50052 list cinescope.reviews.ModerationService
grpcurl -plaintext localhost:50052 describe cinescope.reviews.ModerationService.ModerateReview
```

---

## 1. Успешные сценарии

### 1.1 CreateReview - чистый отзыв (одобрен)
```bash
grpcurl -plaintext -d '{
  "user_id": "user123",
  "movie_id": 1,
  "text": "Отличный фильм! Очень понравился!",
  "rating": 5
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемый результат:**
```json
{
  "review": {
    "user_id": "user123",
    "movie_id": 1,
    "hidden": false,
    "text": "Отличный фильм! Очень понравился!",
    "rating": 5,
    "created_at": "2025-11-25T14:30:00.123456"
  },
  "moderation": {
    "action": "approved",
    "reason": ""
  }
}
```

### 1.2 CreateReview - отзыв с матом (отклонен)
```bash
grpcurl -plaintext -d '{
  "user_id": "user456",
  "movie_id": 1,
  "text": "This movie is shit and boring",
  "rating": 1
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемый результат:**
```json
{
  "review": {
    "user_id": "user456",
    "movie_id": 1,
    "hidden": true,
    "text": "This movie is shit and boring",
    "rating": 1,
    "created_at": "2025-11-25T14:31:00.123456"
  },
  "moderation": {
    "action": "rejected",
    "reason": "profanity detected"
  }
}
```

### 1.3 GetReview - получить отзыв по ключу
```bash
grpcurl -plaintext -d '{
  "user_id": "user123",
  "movie_id": 1
}' localhost:50051 cinescope.reviews.ReviewService/GetReview
```

**Ожидаемый результат:**
```json
{
  "review": {
    "user_id": "user123",
    "movie_id": 1,
    "hidden": false,
    "text": "Отличный фильм! Очень понравился!",
    "rating": 5,
    "created_at": "2025-11-25T14:30:00.123456"
  }
}
```

### 1.4 ListReviews - список отзывов для фильма
```bash
grpcurl -plaintext -d '{
  "movie_id": 1,
  "limit": 10,
  "offset": 0,
  "show_hidden": false
}' localhost:50051 cinescope.reviews.ReviewService/ListReviews
```

**Ожидаемый результат:**
```json
{
  "reviews": [
    {
      "user_id": "user123",
      "movie_id": 1,
      "hidden": false,
      "text": "Отличный фильм! Очень понравился!",
      "rating": 5,
      "created_at": "2025-11-25T14:30:00.123456"
    }
  ],
  "total": 1
}
```

### 1.5 ListReviews - показать скрытые отзывы
```bash
grpcurl -plaintext -d '{
  "movie_id": 1,
  "limit": 10,
  "offset": 0,
  "show_hidden": true
}' localhost:50051 cinescope.reviews.ReviewService/ListReviews
```

**Ожидаемый результат:**
```json
{
  "reviews": [
    {
      "user_id": "user123",
      "movie_id": 1,
      "hidden": false,
      "text": "Отличный фильм! Очень понравился!",
      "rating": 5,
      "created_at": "2025-11-25T14:30:00.123456"
    },
    {
      "user_id": "user456",
      "movie_id": 1,
      "hidden": true,
      "text": "This movie is shit and boring",
      "rating": 1,
      "created_at": "2025-11-25T14:31:00.123456"
    }
  ],
  "total": 2
}
```

### 1.6 GetModerationHistory - история модераций
```bash
grpcurl -plaintext -d '{
  "user_id": "user123",
  "movie_id": 1
}' localhost:50052 cinescope.reviews.ModerationService/GetModerationHistory
```

**Ожидаемый результат:**
```json
{
  "history": [
    {
      "id": 1,
      "review_user_id": "user123",
      "review_movie_id": 1,
      "action": "approved",
      "reason": "",
      "moderated_by": "auto",
      "created_at": "2025-11-25T14:30:00.123456"
    }
  ]
}
```

### 1.7 GetModerationStats - статистика модерации
```bash
grpcurl -plaintext -d '{}' localhost:50052 cinescope.reviews.ModerationService/GetModerationStats
```

**Ожидаемый результат:**
```json
{
  "total": 2,
  "approved": 1,
  "rejected": 1,
  "pending": 0
}
```

---

## 2. Валидационные ошибки

### 2.1 Пустой текст отзыва
```bash
grpcurl -plaintext -d '{
  "user_id": "user789",
  "movie_id": 1,
  "text": "",
  "rating": 3
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемая ошибка:**
```
ERROR:
  Code: InvalidArgument
  Message: Review text cannot be empty
```

### 2.2 Короткий текст (< 10 символов)
```bash
grpcurl -plaintext -d '{
  "user_id": "user789",
  "movie_id": 1,
  "text": "Bad",
  "rating": 1
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемая ошибка:**
```
ERROR:
  Code: InvalidArgument
  Message: Review too short
```

### 2.3 Длинный текст (> 1000 символов)
```bash
grpcurl -plaintext -d '{
  "user_id": "user789",
  "movie_id": 1,
  "text": "'"$(printf 'a%.0s' {1..1001})"'",
  "rating": 3
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемая ошибка:**
```
ERROR:
  Code: InvalidArgument
  Message: Review too long
```

### 2.4 Невалидный rating (не 1-5)
```bash
grpcurl -plaintext -d '{
  "user_id": "user789",
  "movie_id": 1,
  "text": "Average movie honestly speaking",
  "rating": 6
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемая ошибка:**
```
ERROR:
  Code: InvalidArgument
  Message: Rating must be between 1 and 5
```

### 2.5 Дубликат отзыва (user_id + movie_id уже существует)
```bash
# Первый раз - успех
grpcurl -plaintext -d '{
  "user_id": "user999",
  "movie_id": 1,
  "text": "Great movie with awesome plot",
  "rating": 5
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview

# Второй раз с теми же user_id и movie_id - ошибка
grpcurl -plaintext -d '{
  "user_id": "user999",
  "movie_id": 1,
  "text": "Changed my mind, not so great",
  "rating": 3
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемая ошибка:**
```
ERROR:
  Code: AlreadyExists
  Message: Review already exists
```

### 2.6 Несуществующий movie_id
```bash
grpcurl -plaintext -d '{
  "user_id": "user789",
  "movie_id": 999999,
  "text": "This is a review for non-existing movie",
  "rating": 3
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемая ошибка:**
```
ERROR:
  Code: NotFound
  Message: Movie with ID 999999 not found
```

### 2.7 Несуществующий user_id
```bash
grpcurl -plaintext -d '{
  "user_id": "nonexistent_user_99999",
  "movie_id": 1,
  "text": "Review from ghost user account",
  "rating": 4
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемая ошибка:**
```
ERROR:
  Code: NotFound
  Message: User with ID nonexistent_user_99999 not found
```

---

## 3. Пустые ответы

### 3.1 ListReviews для фильма без отзывов
```bash
grpcurl -plaintext -d '{
  "movie_id": 2,
  "limit": 10,
  "offset": 0,
  "show_hidden": false
}' localhost:50051 cinescope.reviews.ReviewService/ListReviews
```

**Ожидаемый результат:**
```json
{
  "reviews": [],
  "total": 0
}
```

### 3.2 GetModerationHistory для несуществующего отзыва
```bash
grpcurl -plaintext -d '{
  "user_id": "nonexistent",
  "movie_id": 999
}' localhost:50052 cinescope.reviews.ModerationService/GetModerationHistory
```

**Ожидаемый результат:**
```json
{
  "history": []
}
```

### 3.3 GetModerationStats когда нет данных
```bash
# Удалить все данные из moderation_log, затем:
grpcurl -plaintext -d '{}' localhost:50052 cinescope.reviews.ModerationService/GetModerationStats
```

**Ожидаемый результат:**
```json
{
  "total": 0,
  "approved": 0,
  "rejected": 0,
  "pending": 0
}
```

### 3.4 GetReview для несуществующего отзыва
```bash
grpcurl -plaintext -d '{
  "user_id": "ghost",
  "movie_id": 999
}' localhost:50051 cinescope.reviews.ReviewService/GetReview
```

**Ожидаемая ошибка:**
```
ERROR:
  Code: NotFound
  Message: Review not found
```

---

## 4. Тестирование таймаутов и retry

### 4.1 Moderation Service недоступен
```bash
# Остановить Moderation Service, затем попробовать создать отзыв
docker stop moderation-service
# или
kubectl scale deployment moderation-service --replicas=0 -n dev

# Создание отзыва (должно быть 3 retry по 1s/2s/4s)
grpcurl -plaintext -d '{
  "user_id": "user111",
  "movie_id": 1,
  "text": "Testing unavailable service scenario",
  "rating": 4
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемая ошибка (после 3 retry):**
```
ERROR:
  Code: Unavailable
  Message: Moderation service temporarily unavailable
```

### 4.2 Database недоступен
```bash
# Остановить PostgreSQL
docker stop postgres
# или
kubectl scale statefulset postgres --replicas=0 -n dev

# Попытка создать отзыв
grpcurl -plaintext -d '{
  "user_id": "user222",
  "movie_id": 1,
  "text": "Testing database unavailability",
  "rating": 3
}' localhost:50051 cinescope.reviews.ReviewService/CreateReview
```

**Ожидаемая ошибка:**
```
ERROR:
  Code: Unavailable
  Message: Database connection failed
```

---

## 5. Дополнительные сценарии

### 5.1 UpdateReviewVisibility (напрямую)
```bash
grpcurl -plaintext -d '{
  "user_id": "user123",
  "movie_id": 1,
  "hidden": true
}' localhost:50051 cinescope.reviews.ReviewService/UpdateReviewVisibility
```

**Ожидаемый результат:**
```json
{
  "success": true
}
```

### 5.2 ModerateReview (напрямую из Moderation Service)
```bash
grpcurl -plaintext -d '{
  "user_id": "user123",
  "movie_id": 1,
  "text": "Clean review without profanity"
}' localhost:50052 cinescope.reviews.ModerationService/ModerateReview
```

**Ожидаемый результат:**
```json
{
  "action": "approved",
  "reason": ""
}
```

### 5.3 ModerateReview с матом
```bash
grpcurl -plaintext -d '{
  "user_id": "user456",
  "movie_id": 1,
  "text": "This is a fuck bad movie"
}' localhost:50052 cinescope.reviews.ModerationService/ModerateReview
```

**Ожидаемый результат:**
```json
{
  "action": "rejected",
  "reason": "profanity detected"
}
```

---

## Логи и отладка

### Просмотр логов (JSON формат)
```bash
# Docker
docker logs -f review-service
docker logs -f moderation-service

# Kubernetes
kubectl logs -f deployment/review-service -n dev
kubectl logs -f deployment/moderation-service -n dev

# Фильтрация по request_id
kubectl logs deployment/review-service -n dev | grep "request_id.*abc-123"
```

### Health Check
```bash
# Review Service
grpcurl -plaintext localhost:50051 grpc.health.v1.Health/Check

# Moderation Service
grpcurl -plaintext localhost:50052 grpc.health.v1.Health/Check
```

**Ожидаемый результат:**
```json
{
  "status": "SERVING"
}
```

---

## База данных

### Проверка данных в PostgreSQL
```bash
# Подключение к БД
psql -h localhost -U postgres -d db_movies

# Просмотр отзывов
SELECT * FROM reviews ORDER BY created_at DESC LIMIT 10;

# Просмотр логов модерации
SELECT * FROM moderation_log ORDER BY created_at DESC LIMIT 10;

# Статистика модерации
SELECT
    action,
    COUNT(*) as count
FROM moderation_log
GROUP BY action;
```

---

## Troubleshooting

### Проблема: "Movie with ID X not found"
**Решение:** Убедитесь, что movie_id существует в таблице `movies`:
```sql
INSERT INTO movies (id, title) VALUES (1, 'Test Movie');
```

### Проблема: "User with ID X not found"
**Решение:** Убедитесь, что user_id существует в таблице `users`:
```sql
INSERT INTO users (id, username) VALUES ('user123', 'testuser');
```

### Проблема: Connection refused
**Решение:** Проверьте, что сервисы запущены:
```bash
# Локально
ps aux | grep server.py

# Docker
docker ps | grep review-service

# Kubernetes
kubectl get pods -n dev
```

---

## Технологический стек

- **Язык**: Python 3.11
- **Framework**: grpcio 1.60.0
- **БД**: PostgreSQL (psycopg2-binary)
- **Логи**: structlog (JSON формат)
- **Health**: grpc-health-checking
- **Reflection**: grpc-reflection (для grpcurl)

## Структура проекта

```
grpc_services/
├── proto/
│   └── reviews.proto                    # Protocol Buffers определения
├── services/
│   ├── review-service/
│   │   ├── server.py                    # Review Service
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   ├── generate_proto.sh
│   │   └── README.md
│   └── moderation-service/
│       ├── server.py                    # Moderation Service
│       ├── requirements.txt
│       ├── Dockerfile
│       ├── generate_proto.sh
│       └── README.md
├── k8s/
│   ├── namespace.yaml
│   ├── secret-example.yaml
│   ├── configmap.yaml
│   ├── review-service-deployment.yaml
│   ├── moderation-service-deployment.yaml
│   └── README.md
├── db/
│   └── schema.sql                       # Схема БД
├── docs/
│   ├── TEST_SCENARIOS.md               # Тестовые сценарии
│   └── k8s-example.yaml
├── PROJECT_BRIEF.md
└── README.md                           # Этот файл
```

## Автор
Система разработана для обучения QA инженеров тестированию gRPC API.

## Лицензия
MIT

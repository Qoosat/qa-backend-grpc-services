# Review Service

gRPC сервис для CRUD операций с отзывами на фильмы.

## Порт
- gRPC: **50051**
- Health: **8080**

## Методы

### CreateReview
Создать новый отзыв (сохраняется с hidden=true, затем вызывается модерация).

### GetReview
Получить отзыв по составному ключу (user_id, movie_id).

### ListReviews
Список отзывов с фильтрацией и пагинацией.

### UpdateReviewVisibility
Обновить видимость отзыва (вызывается из Moderation Service).

## Локальная разработка

### Генерация proto файлов
```bash
bash generate_proto.sh
```

### Установка зависимостей
```bash
pip install -r requirements.txt
```

### Запуск сервиса
```bash
python server.py
```

## Docker

### Build
```bash
docker build -t nklrif/review-service:latest -f services/review-service/Dockerfile .
```

### Run
```bash
docker run -p 50051:50051 --env-file .env nklrif/review-service:latest
```

## Зависимости
- PostgreSQL (таблица reviews)
- Moderation Service (для автоматической модерации)

## Валидации
- text: не пустой, 10-1000 символов
- rating: 1-5
- movie_id: должен существовать в таблице movies
- user_id: должен существовать в таблице users
- Дубликаты по (user_id, movie_id) запрещены

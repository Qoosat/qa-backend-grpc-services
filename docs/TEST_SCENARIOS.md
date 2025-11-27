# Тестовые сценарии для QA

## 1. Успешные запросы

### CreateReview - валидный отзыв
**Request:**
```json
{
  "user_id": "user123",
  "movie_id": 42,
  "text": "Отличный фильм!",
  "rating": 5
}
```
**Expected:** review_id, status="approved", hidden=false

### GetReview - получение по ключу
**Request:**
```json
{
  "user_id": "user123",
  "movie_id": 42
}
```
**Expected:** полные данные отзыва

### ListReviews - с пагинацией
**Request:**
```json
{
  "movie_id": 42,
  "limit": 10,
  "offset": 0,
  "show_hidden": false
}
```
**Expected:** массив видимых отзывов

---

## 2. Валидации (ошибки)

### Пустой текст
**Request:** text = ""
**Expected:** INVALID_ARGUMENT "Review text cannot be empty"

### Короткий текст
**Request:** text = "Bad"
**Expected:** INVALID_ARGUMENT "Review too short"

### Невалидный rating
**Request:** rating = 6
**Expected:** INVALID_ARGUMENT "Rating must be between 1 and 5"

### Дубликат отзыва
**Request:** повторный CreateReview с теми же user_id, movie_id
**Expected:** ALREADY_EXISTS

---

## 3. Бизнес-логика

### Отзыв с матом
**Request:** text = "This movie is shit"
**Expected:** 
- hidden=true
- moderation_log: action='rejected', reason='profanity detected'

### Несуществующий movie_id
**Request:** movie_id = 999999
**Expected:** NOT_FOUND "Movie with ID 999999 not found"

---

## 4. Пустые ответы

### ListReviews для фильма без отзывов
**Request:** movie_id = 1 (без отзывов)
**Expected:** reviews=[], total=0

### GetModerationHistory для нового отзыва
**Request:** review без модераций
**Expected:** history=[]

---

## 5. Таймауты

### Moderation Service недоступен
**Setup:** остановить moderation-service
**Expected:** UNAVAILABLE "Moderation service temporarily unavailable"

### Slow query в БД
**Setup:** добавить pg_sleep в запрос
**Expected:** DEADLINE_EXCEEDED
```
# Moderation Service

gRPC сервис для автоматической модерации отзывов на фильмы.

## Порт
- gRPC: **50052**
- Health: **8081**

## Методы

### ModerateReview
Проверить текст отзыва по правилам модерации.

**Логика:**
- Проверка на запрещенные слова из `PROFANITY_WORDS`
- Если найдены матерные слова: `action='rejected'`, `reason='profanity detected'`, `hidden=true`
- Если текст чистый: `action='approved'`, `reason=null`, `hidden=false`
- Результат сохраняется в `moderation_log`
- Вызывается `UpdateReviewVisibility` в Review Service

### GetModerationHistory
Получить историю модераций для отзыва по ключу (user_id, movie_id).

### GetModerationStats
Получить общую статистику модерации:
- `total` - всего модераций
- `approved` - одобренных
- `rejected` - отклоненных
- `pending` - в ожидании

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
docker build -t nklrif/moderation-service:latest -f services/moderation-service/Dockerfile .
```

### Run
```bash
docker run -p 50052:50052 --env-file .env nklrif/moderation-service:latest
```

## Зависимости
- PostgreSQL (таблица moderation_log)
- Review Service (для обновления видимости отзывов)

## Конфигурация
Запрещенные слова настраиваются через переменную окружения `PROFANITY_WORDS` (через запятую):
```bash
PROFANITY_WORDS=badword1,badword2,fuck,shit
```

## Workflow
1. Review Service создает отзыв с `hidden=true`
2. Review Service вызывает `ModerateReview`
3. Moderation Service проверяет текст на profanity
4. Moderation Service сохраняет результат в `moderation_log`
5. Moderation Service вызывает `UpdateReviewVisibility` в Review Service
6. Review Service обновляет `hidden` в БД

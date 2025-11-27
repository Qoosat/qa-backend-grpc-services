#!/usr/bin/env python3
"""
Review Service - CRUD операции с отзывами на фильмы
Порт: 50051
"""

import os
import sys
import signal
import time
import uuid
from concurrent import futures
from datetime import datetime

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection
import psycopg2
from psycopg2 import pool, sql, extras
import structlog

# Импорт сгенерированных proto файлов
import reviews_pb2
import reviews_pb2_grpc

# ============================================================================
# Logging Configuration
# ============================================================================

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# ============================================================================
# Configuration
# ============================================================================

DATABASE_URL = os.getenv('DATABASE_URL_POSTGRES', 'postgresql://postgres:password@localhost:5432/db_movies')
DB_POOL_MIN_SIZE = int(os.getenv('DB_POOL_MIN_SIZE', '2'))
DB_POOL_MAX_SIZE = int(os.getenv('DB_POOL_MAX_SIZE', '10'))
MODERATION_SERVICE_HOST = os.getenv('MODERATION_SERVICE_HOST', 'localhost')
MODERATION_SERVICE_PORT = int(os.getenv('MODERATION_SERVICE_PORT', '50052'))
GRPC_SERVER_MAX_WORKERS = int(os.getenv('GRPC_SERVER_MAX_WORKERS', '10'))
GRPC_KEEPALIVE_TIME_MS = int(os.getenv('GRPC_KEEPALIVE_TIME_MS', '10000'))
GRPC_KEEPALIVE_TIMEOUT_MS = int(os.getenv('GRPC_KEEPALIVE_TIMEOUT_MS', '5000'))
MODERATION_TIMEOUT_SECONDS = int(os.getenv('MODERATION_TIMEOUT_SECONDS', '5'))

# ============================================================================
# Database Connection Pool
# ============================================================================

db_pool = None

def init_db_pool():
    """Инициализация connection pool для PostgreSQL"""
    global db_pool
    try:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            DB_POOL_MIN_SIZE,
            DB_POOL_MAX_SIZE,
            DATABASE_URL
        )
        logger.info("database_pool_initialized", min_size=DB_POOL_MIN_SIZE, max_size=DB_POOL_MAX_SIZE)
        return db_pool
    except Exception as e:
        logger.error("database_pool_init_failed", error=str(e))
        raise

def get_db_connection():
    """Получить соединение из пула"""
    try:
        return db_pool.getconn()
    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        raise

def release_db_connection(conn):
    """Вернуть соединение в пул"""
    if conn:
        db_pool.putconn(conn)

def close_db_pool():
    """Закрыть все соединения в пуле"""
    if db_pool:
        db_pool.closeall()
        logger.info("database_pool_closed")

# ============================================================================
# Retry Logic with Exponential Backoff
# ============================================================================

def retry_with_backoff(func, max_retries=3, initial_delay=1.0):
    """
    Retry функции с exponential backoff
    max_retries: 3 попытки
    delays: 1s, 2s, 4s
    """
    for attempt in range(max_retries):
        try:
            return func()
        except grpc.RpcError as e:
            if attempt == max_retries - 1:
                raise
            delay = initial_delay * (2 ** attempt)
            logger.warning("retry_attempt", attempt=attempt + 1, delay=delay, error=str(e))
            time.sleep(delay)
    raise Exception("Max retries exceeded")

# ============================================================================
# Review Service Implementation
# ============================================================================

class ReviewServiceServicer(reviews_pb2_grpc.ReviewServiceServicer):
    """Реализация ReviewService"""

    def CreateReview(self, request, context):
        """Создать новый отзыв"""
        request_id = str(uuid.uuid4())
        log = logger.bind(request_id=request_id, method="CreateReview", user_id=request.user_id, movie_id=request.movie_id)
        log.info("create_review_started")

        # Валидация входных данных
        try:
            self._validate_create_review_request(request)
        except ValueError as e:
            log.error("validation_failed", error=str(e))
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(e))
            return reviews_pb2.CreateReviewResponse()

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Проверка существования movie_id
            cursor.execute("SELECT id FROM movies WHERE id = %s", (request.movie_id,))
            if not cursor.fetchone():
                log.error("movie_not_found", movie_id=request.movie_id)
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"Movie with ID {request.movie_id} not found")
                return reviews_pb2.CreateReviewResponse()

            # Проверка существования user_id
            cursor.execute("SELECT id FROM users WHERE id = %s", (request.user_id,))
            if not cursor.fetchone():
                log.error("user_not_found", user_id=request.user_id)
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"User with ID {request.user_id} not found")
                return reviews_pb2.CreateReviewResponse()

            # Проверка на дубликат
            cursor.execute(
                "SELECT user_id FROM reviews WHERE user_id = %s AND movie_id = %s",
                (request.user_id, request.movie_id)
            )
            if cursor.fetchone():
                log.error("review_already_exists")
                context.set_code(grpc.StatusCode.ALREADY_EXISTS)
                context.set_details("Review already exists")
                return reviews_pb2.CreateReviewResponse()

            # Создание отзыва с hidden=true
            cursor.execute(
                """
                INSERT INTO reviews (user_id, movie_id, text, rating, hidden, created_at)
                VALUES (%s, %s, %s, %s, true, NOW())
                RETURNING user_id, movie_id, text, rating, hidden, created_at
                """,
                (request.user_id, request.movie_id, request.text, request.rating)
            )
            row = cursor.fetchone()
            conn.commit()

            # Создание объекта Review
            review = reviews_pb2.Review(
                user_id=row[0],
                movie_id=row[1],
                text=row[2],
                rating=row[3],
                hidden=row[4],
                created_at=row[5].isoformat()
            )

            log.info("review_created", hidden=True)

            # Вызов Moderation Service с retry logic
            try:
                moderation_result = self._call_moderation_service(request.user_id, request.movie_id, request.text, log)
            except Exception as e:
                log.error("moderation_service_unavailable", error=str(e))
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details("Moderation service temporarily unavailable")
                return reviews_pb2.CreateReviewResponse()

            log.info("create_review_completed", action=moderation_result.action)

            return reviews_pb2.CreateReviewResponse(
                review=review,
                moderation=moderation_result
            )

        except Exception as e:
            if conn:
                conn.rollback()
            log.error("create_review_failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal error: {str(e)}")
            return reviews_pb2.CreateReviewResponse()
        finally:
            if conn:
                if cursor:
                    cursor.close()
                release_db_connection(conn)

    def GetReview(self, request, context):
        """Получить отзыв по составному ключу"""
        request_id = str(uuid.uuid4())
        log = logger.bind(request_id=request_id, method="GetReview", user_id=request.user_id, movie_id=request.movie_id)
        log.info("get_review_started")

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT user_id, movie_id, text, rating, hidden, created_at
                FROM reviews
                WHERE user_id = %s AND movie_id = %s
                """,
                (request.user_id, request.movie_id)
            )
            row = cursor.fetchone()

            if not row:
                log.error("review_not_found")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("Review not found")
                return reviews_pb2.GetReviewResponse()

            review = reviews_pb2.Review(
                user_id=row[0],
                movie_id=row[1],
                text=row[2],
                rating=row[3],
                hidden=row[4],
                created_at=row[5].isoformat()
            )

            log.info("get_review_completed")
            return reviews_pb2.GetReviewResponse(review=review)

        except Exception as e:
            log.error("get_review_failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal error: {str(e)}")
            return reviews_pb2.GetReviewResponse()
        finally:
            if conn:
                if cursor:
                    cursor.close()
                release_db_connection(conn)

    def ListReviews(self, request, context):
        """Список отзывов с фильтрацией и пагинацией"""
        request_id = str(uuid.uuid4())
        log = logger.bind(request_id=request_id, method="ListReviews", movie_id=request.movie_id)
        log.info("list_reviews_started")

        limit = request.limit if request.limit > 0 else 10
        offset = request.offset if request.offset >= 0 else 0

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Построение запроса с фильтрацией
            query = """
                SELECT user_id, movie_id, text, rating, hidden, created_at
                FROM reviews
                WHERE movie_id = %s
            """
            params = [request.movie_id]

            if not request.show_hidden:
                query += " AND hidden = false"

            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Получение общего количества
            count_query = "SELECT COUNT(*) FROM reviews WHERE movie_id = %s"
            count_params = [request.movie_id]
            if not request.show_hidden:
                count_query += " AND hidden = false"
            cursor.execute(count_query, count_params)
            total = cursor.fetchone()[0]

            reviews = []
            for row in rows:
                reviews.append(reviews_pb2.Review(
                    user_id=row[0],
                    movie_id=row[1],
                    text=row[2],
                    rating=row[3],
                    hidden=row[4],
                    created_at=row[5].isoformat()
                ))

            log.info("list_reviews_completed", count=len(reviews), total=total)
            return reviews_pb2.ListReviewsResponse(reviews=reviews, total=total)

        except Exception as e:
            log.error("list_reviews_failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal error: {str(e)}")
            return reviews_pb2.ListReviewsResponse()
        finally:
            if conn:
                if cursor:
                    cursor.close()
                release_db_connection(conn)

    def UpdateReviewVisibility(self, request, context):
        """Обновить видимость отзыва (вызывается из Moderation Service)"""
        request_id = str(uuid.uuid4())
        log = logger.bind(request_id=request_id, method="UpdateReviewVisibility",
                         user_id=request.user_id, movie_id=request.movie_id, hidden=request.hidden)
        log.info("update_visibility_started")

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE reviews
                SET hidden = %s
                WHERE user_id = %s AND movie_id = %s
                """,
                (request.hidden, request.user_id, request.movie_id)
            )
            conn.commit()

            success = cursor.rowcount > 0
            log.info("update_visibility_completed", success=success)

            return reviews_pb2.UpdateReviewVisibilityResponse(success=success)

        except Exception as e:
            if conn:
                conn.rollback()
            log.error("update_visibility_failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal error: {str(e)}")
            return reviews_pb2.UpdateReviewVisibilityResponse(success=False)
        finally:
            if conn:
                if cursor:
                    cursor.close()
                release_db_connection(conn)

    def _validate_create_review_request(self, request):
        """Валидация CreateReview запроса"""
        if not request.text or len(request.text.strip()) == 0:
            raise ValueError("Review text cannot be empty")
        if len(request.text) < 10:
            raise ValueError("Review too short")
        if len(request.text) > 1000:
            raise ValueError("Review too long")
        if request.rating < 1 or request.rating > 5:
            raise ValueError("Rating must be between 1 and 5")

    def _call_moderation_service(self, user_id, movie_id, text, log):
        """Вызов Moderation Service с retry logic"""
        def call():
            channel = grpc.insecure_channel(
                f'{MODERATION_SERVICE_HOST}:{MODERATION_SERVICE_PORT}',
                options=[
                    ('grpc.keepalive_time_ms', GRPC_KEEPALIVE_TIME_MS),
                    ('grpc.keepalive_timeout_ms', GRPC_KEEPALIVE_TIMEOUT_MS),
                ]
            )
            stub = reviews_pb2_grpc.ModerationServiceStub(channel)

            moderate_request = reviews_pb2.ModerateReviewRequest(
                user_id=user_id,
                movie_id=movie_id,
                text=text
            )

            try:
                response = stub.ModerateReview(
                    moderate_request,
                    timeout=MODERATION_TIMEOUT_SECONDS
                )
                log.info("moderation_service_called", action=response.action)

                moderation_result = reviews_pb2.ModerationResult(
                    action=response.action,
                    reason=response.reason if response.reason else ""
                )
                return moderation_result
            finally:
                channel.close()

        return retry_with_backoff(call, max_retries=3, initial_delay=1.0)

# ============================================================================
# gRPC Server
# ============================================================================

def serve():
    """Запуск gRPC сервера"""
    # Инициализация БД пула
    init_db_pool()

    # Создание gRPC сервера
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=GRPC_SERVER_MAX_WORKERS),
        options=[
            ('grpc.keepalive_time_ms', GRPC_KEEPALIVE_TIME_MS),
            ('grpc.keepalive_timeout_ms', GRPC_KEEPALIVE_TIMEOUT_MS),
            ('grpc.http2.max_pings_without_data', 0),
            ('grpc.http2.min_time_between_pings_ms', 10000),
            ('grpc.http2.min_ping_interval_without_data_ms', 5000),
        ]
    )

    # Регистрация сервиса
    reviews_pb2_grpc.add_ReviewServiceServicer_to_server(ReviewServiceServicer(), server)

    # Health checking
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set("cinescope.reviews.ReviewService", health_pb2.HealthCheckResponse.SERVING)

    # gRPC Reflection
    SERVICE_NAMES = (
        reviews_pb2.DESCRIPTOR.services_by_name['ReviewService'].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)

    # Запуск сервера
    server.add_insecure_port('[::]:50051')
    server.start()
    logger.info("review_service_started", port=50051)

    # Graceful shutdown
    def handle_sigterm(signum, frame):
        logger.info("received_sigterm", signal=signum)
        server.stop(grace=10)
        close_db_pool()
        logger.info("review_service_stopped")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=10)
        close_db_pool()
        logger.info("review_service_stopped")

if __name__ == '__main__':
    serve()

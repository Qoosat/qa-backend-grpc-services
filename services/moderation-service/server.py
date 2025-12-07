#!/usr/bin/env python3
"""
Moderation Service - Автоматическая модерация отзывов
Порт: 50052
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
import logging

# Импорт сгенерированных proto файлов
import reviews_pb2
import reviews_pb2_grpc

# ============================================================================
# Logging Configuration
# ============================================================================
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
    format='%(message)s',
    stream=sys.stdout,
    level=LOG_LEVEL
)

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
REVIEW_SERVICE_HOST = os.getenv('REVIEW_SERVICE_HOST', 'localhost')
REVIEW_SERVICE_PORT = int(os.getenv('REVIEW_SERVICE_PORT', '50051'))
GRPC_SERVER_MAX_WORKERS = int(os.getenv('GRPC_SERVER_MAX_WORKERS', '10'))
GRPC_KEEPALIVE_TIME_MS = int(os.getenv('GRPC_KEEPALIVE_TIME_MS', '10000'))
GRPC_KEEPALIVE_TIMEOUT_MS = int(os.getenv('GRPC_KEEPALIVE_TIMEOUT_MS', '5000'))
PROFANITY_WORDS_STR = os.getenv('PROFANITY_WORDS', 'badword1,badword2,fuck,shit')
PROFANITY_WORDS = set(word.strip().lower() for word in PROFANITY_WORDS_STR.split(','))

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
# Profanity Detection
# ============================================================================

def contains_profanity(text):
    """
    Проверка текста на запрещенные слова
    Returns: (bool, list) - (найдены ли мат. слова, список найденных слов)
    """
    words = text.lower().split()
    found_profanity = []

    for word in words:
        # Убираем знаки препинания
        clean_word = ''.join(c for c in word if c.isalnum())
        if clean_word in PROFANITY_WORDS:
            found_profanity.append(clean_word)

    return len(found_profanity) > 0, found_profanity

# ============================================================================
# Moderation Service Implementation
# ============================================================================

class ModerationServiceServicer(reviews_pb2_grpc.ModerationServiceServicer):
    """Реализация ModerationService"""

    def ModerateReview(self, request, context):
        """Проверить текст отзыва по правилам модерации"""
        request_id = str(uuid.uuid4())
        log = logger.bind(request_id=request_id, method="ModerateReview",
                         user_id=request.user_id, movie_id=request.movie_id)
        log.info("moderate_review_started")

        conn = None
        try:
            # Проверка на profanity
            has_profanity, found_words = contains_profanity(request.text)

            if has_profanity:
                action = 'rejected'
                reason = 'profanity detected'
                hidden = True
                log.info("profanity_detected", words=found_words)
            else:
                action = 'approved'
                reason = None
                hidden = False
                log.info("review_approved")

            # Сохранение в moderation_log
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO moderation_log (review_user_id, review_movie_id, action, reason, moderated_by, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (request.user_id, request.movie_id, action, reason, 'auto')
            )
            conn.commit()

            log.info("moderation_log_saved", action=action)

            # Вызов Review Service для обновления видимости
            try:
                self._update_review_visibility(request.user_id, request.movie_id, hidden, log)
            except Exception as e:
                log.error("failed_to_update_visibility", error=str(e))
                # Продолжаем работу, даже если не удалось обновить visibility

            log.info("moderate_review_completed", action=action)

            return reviews_pb2.ModerateReviewResponse(
                action=action,
                reason=reason if reason else ""
            )

        except Exception as e:
            if conn:
                conn.rollback()
            log.error("moderate_review_failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal error: {str(e)}")
            return reviews_pb2.ModerateReviewResponse()
        finally:
            if conn:
                if cursor:
                    cursor.close()
                release_db_connection(conn)

    def GetModerationHistory(self, request, context):
        """Получить историю модераций для отзыва"""
        request_id = str(uuid.uuid4())
        log = logger.bind(request_id=request_id, method="GetModerationHistory",
                         user_id=request.user_id, movie_id=request.movie_id)
        log.info("get_moderation_history_started")

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, review_user_id, review_movie_id, action, reason, moderated_by, created_at
                FROM moderation_log
                WHERE review_user_id = %s AND review_movie_id = %s
                ORDER BY created_at DESC
                """,
                (request.user_id, request.movie_id)
            )
            rows = cursor.fetchall()

            history = []
            for row in rows:
                history.append(reviews_pb2.ModerationLogEntry(
                    id=row[0],
                    review_user_id=row[1],
                    review_movie_id=row[2],
                    action=row[3],
                    reason=row[4] if row[4] else "",
                    moderated_by=row[5],
                    created_at=row[6].isoformat()
                ))

            log.info("get_moderation_history_completed", count=len(history))
            return reviews_pb2.GetModerationHistoryResponse(history=history)

        except Exception as e:
            log.error("get_moderation_history_failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal error: {str(e)}")
            return reviews_pb2.GetModerationHistoryResponse()
        finally:
            if conn:
                if cursor:
                    cursor.close()
                release_db_connection(conn)

    def GetModerationStats(self, request, context):
        """Получить статистику модерации"""
        request_id = str(uuid.uuid4())
        log = logger.bind(request_id=request_id, method="GetModerationStats")
        log.info("get_moderation_stats_started")

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Получение общей статистики
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN action = 'approved' THEN 1 ELSE 0 END) as approved,
                    SUM(CASE WHEN action = 'rejected' THEN 1 ELSE 0 END) as rejected,
                    SUM(CASE WHEN action = 'pending' THEN 1 ELSE 0 END) as pending
                FROM moderation_log
                """
            )
            row = cursor.fetchone()

            total = row[0] if row[0] else 0
            approved = row[1] if row[1] else 0
            rejected = row[2] if row[2] else 0
            pending = row[3] if row[3] else 0

            log.info("get_moderation_stats_completed", total=total, approved=approved,
                    rejected=rejected, pending=pending)

            return reviews_pb2.GetModerationStatsResponse(
                total=total,
                approved=approved,
                rejected=rejected,
                pending=pending
            )

        except Exception as e:
            log.error("get_moderation_stats_failed", error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal error: {str(e)}")
            return reviews_pb2.GetModerationStatsResponse()
        finally:
            if conn:
                if cursor:
                    cursor.close()
                release_db_connection(conn)

    def _update_review_visibility(self, user_id, movie_id, hidden, log):
        """Вызов Review Service для обновления видимости отзыва"""
        channel = grpc.insecure_channel(
            f'{REVIEW_SERVICE_HOST}:{REVIEW_SERVICE_PORT}',
            options=[
                ('grpc.keepalive_time_ms', GRPC_KEEPALIVE_TIME_MS),
                ('grpc.keepalive_timeout_ms', GRPC_KEEPALIVE_TIMEOUT_MS),
            ]
        )
        stub = reviews_pb2_grpc.ReviewServiceStub(channel)

        update_request = reviews_pb2.UpdateReviewVisibilityRequest(
            user_id=user_id,
            movie_id=movie_id,
            hidden=hidden
        )

        try:
            response = stub.UpdateReviewVisibility(update_request, timeout=5)
            log.info("review_visibility_updated", success=response.success, hidden=hidden)
            return response.success
        except grpc.RpcError as e:
            log.error("review_visibility_update_failed", error=str(e))
            raise
        finally:
            channel.close()

# ============================================================================
# gRPC Server
# ============================================================================

def serve():
    """Запуск gRPC сервера"""
    # Инициализация БД пула
    init_db_pool()

    logger.info("profanity_words_loaded", count=len(PROFANITY_WORDS), words=list(PROFANITY_WORDS))

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
    reviews_pb2_grpc.add_ModerationServiceServicer_to_server(ModerationServiceServicer(), server)

    # Health checking
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set("cinescope.reviews.ModerationService", health_pb2.HealthCheckResponse.SERVING)

    # gRPC Reflection
    SERVICE_NAMES = (
        reviews_pb2.DESCRIPTOR.services_by_name['ModerationService'].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)

    # Запуск сервера
    server.add_insecure_port('[::]:50052')
    server.start()
    logger.info("moderation_service_started", port=50052)

    # Graceful shutdown
    def handle_sigterm(signum, frame):
        logger.info("received_sigterm", signal=signum)
        server.stop(grace=10)
        close_db_pool()
        logger.info("moderation_service_stopped")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=10)
        close_db_pool()
        logger.info("moderation_service_stopped")

if __name__ == '__main__':
    serve()

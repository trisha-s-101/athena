"""Postgres access for the API. Only api/ talks to the database (CONTRACT.md section 2, rule 2).

The pool is created on first use from DATABASE_URL, so the app still starts (and /health
still answers) when the database is down or the variable is missing.
"""

import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
import psycopg2.pool

# uvicorn's own logger, so messages appear in the app's tmux window next to its startup lines.
logger = logging.getLogger("uvicorn.error")

poolSize = 20
simStartTime = "2026-01-05T00:00:00Z"  # Contract section 3; used until the first clock event arrives.

_pool = None
_poolLock = threading.Lock()
# ThreadedConnectionPool raises when it runs out instead of waiting, so callers queue here first.
_poolSlots = threading.BoundedSemaphore(poolSize)


class DatabaseUnavailable(Exception):
    """DATABASE_URL is missing or Postgres can't be reached."""


def getPool():
    global _pool
    with _poolLock:
        if _pool is None:
            databaseUrl = os.environ.get("DATABASE_URL")
            if not databaseUrl:
                raise DatabaseUnavailable("DATABASE_URL is not set")
            try:
                _pool = psycopg2.pool.ThreadedConnectionPool(1, poolSize, databaseUrl, options="-c timezone=UTC")
            except psycopg2.OperationalError as error:
                raise DatabaseUnavailable(str(error)) from error
        return _pool


def closePool() -> None:
    global _pool
    with _poolLock:
        if _pool is not None:
            _pool.closeall()
            _pool = None


@contextmanager
def transaction():
    """Yields a cursor inside one transaction: commits on success, rolls back on any error."""
    pool = getPool()
    with _poolSlots:
        try:
            connection = pool.getconn()
        except psycopg2.OperationalError as error:
            raise DatabaseUnavailable(str(error)) from error
        broken = False
        try:
            with connection, connection.cursor() as cursor:
                yield cursor
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            broken = True
            raise
        finally:
            pool.putconn(connection, close=broken or connection.closed != 0)


def warnIfDatabaseUrlMissing() -> None:
    if not os.environ.get("DATABASE_URL"):
        logger.warning("DATABASE_URL is not set, so every database endpoint will return 503. "
                       "Stop the app, run: source ~/plateletExchange.env, then start it again.")


def isDatabaseOk() -> bool:
    """Logs the reason when the check fails, so a dbOk of false always comes with an explanation."""
    try:
        with transaction() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except (DatabaseUnavailable, psycopg2.Error) as error:
        logger.warning("Health check: database unavailable: %s", str(error).strip())
        return False


def currentSimTime(cursor) -> str:
    """The latest clock event's time, or the sim start before any clock event."""
    cursor.execute("SELECT at FROM events WHERE type = 'clock' ORDER BY event_number DESC LIMIT 1")
    row = cursor.fetchone()
    return toIsoTime(row[0]) if row else simStartTime


def toIsoTime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

"""Postgres access for the API. Only api/ talks to the database (CONTRACT.md section 2, rule 2).

The pool is created on first use from DATABASE_URL, so the app still starts (and /health
still answers) when the database is down or the variable is missing.
"""

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
import psycopg2.pool

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


def isDatabaseOk() -> bool:
    try:
        with transaction() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except (DatabaseUnavailable, psycopg2.Error):
        return False


def currentSimTime(cursor) -> str:
    """The latest clock event's time, or the sim start before any clock event."""
    cursor.execute("SELECT at FROM events WHERE type = 'clock' ORDER BY event_number DESC LIMIT 1")
    row = cursor.fetchone()
    return toIsoTime(row[0]) if row else simStartTime


def toIsoTime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

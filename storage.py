"""SQLite and optional PostgreSQL storage for the same lesson data."""
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
import sqlite3


@dataclass(frozen=True)
class Postgres:
    dsn: str = field(repr=False)


class StorageUnavailable(Exception):
    pass


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS progress (
        profile TEXT NOT NULL,
        lesson TEXT NOT NULL,
        answers TEXT NOT NULL,
        results TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (profile, lesson)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS machines (
        profile TEXT NOT NULL,
        lesson TEXT NOT NULL,
        state TEXT NOT NULL,
        PRIMARY KEY (profile, lesson)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS custom_tasks (
        id TEXT PRIMARY KEY,
        definition TEXT NOT NULL,
        revision INTEGER NOT NULL
    )
    """,
)


def connect(database):
    if isinstance(database, Postgres):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError("Для PostgreSQL установите зависимости из requirements-postgres.txt.") from error
        return psycopg.connect(database.dsn, row_factory=dict_row, connect_timeout=5,
                               application_name="op01", options="-c statement_timeout=5000 -c lock_timeout=4000")
    db = sqlite3.connect(database, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def execute(db, statement, parameters=()):
    if not isinstance(db, sqlite3.Connection):
        # All statements are static. Values are always bound by the driver.
        statement = statement.replace("?", "%s")
    return db.execute(statement, parameters)


@contextmanager
def request_database(database, *, write=False):
    database_error = sqlite3.OperationalError
    if isinstance(database, Postgres):
        from psycopg import OperationalError
        database_error = OperationalError
    try:
        with closing(connect(database)) as db:
            if write:
                with db:
                    yield db
            else:
                yield db
    except database_error as error:
        raise StorageUnavailable from error


def initialize(database):
    with closing(connect(database)) as db, db:
        if isinstance(database, Postgres):
            execute(db, "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", ("op01:schema",))
        for statement in SCHEMA:
            execute(db, statement)


def lock_lesson(db, profile, lesson):
    if isinstance(db, sqlite3.Connection):
        db.execute("BEGIN IMMEDIATE")
    else:
        execute(db, "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
                (f"op01:lesson:{profile}:{lesson}",))

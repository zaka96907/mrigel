"""Database engine and session. SQLite locally, Postgres in production (DATABASE_URL)."""

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


def _normalise_url(url: str) -> str:
    # Hosts (Render, Neon, Supabase) hand out postgres:// or postgresql:// URLs; use the psycopg 3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _normalise_url(settings.database_url)
_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (registers the tables)

    Base.metadata.create_all(bind=engine)
    add_missing_columns()


def add_missing_columns() -> list[str]:
    """create_all makes new tables but never touches existing ones. Add any new nullable or defaulted
    column so an older database keeps working after an upgrade. Returns what was added."""
    from sqlalchemy import inspect, text

    added = []
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                default = ""
                if column.default is not None and getattr(column.default, "is_scalar", False):
                    value = column.default.arg
                    if isinstance(value, bool):
                        default = " DEFAULT " + ("TRUE" if value else "FALSE")
                    elif isinstance(value, (int, float)):
                        default = f" DEFAULT {value}"
                    elif isinstance(value, str):
                        default = " DEFAULT '" + value.replace("'", "''") + "'"
                elif str(column.type) == "JSON":
                    try:
                        empty = column.default.arg(None) if column.default is not None else []
                    except TypeError:
                        empty = []
                    default = " DEFAULT '{}'" if isinstance(empty, dict) else " DEFAULT '[]'"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl_type}{default}'))
                added.append(f"{table.name}.{column.name}")
    return added

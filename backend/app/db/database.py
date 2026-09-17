"""SQLite persistence layer (SQLAlchemy)."""
import os
from typing import List

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from ..config import settings

os.makedirs(os.path.dirname(os.path.abspath(settings.DB_PATH)), exist_ok=True)

engine = create_engine(
    f"sqlite:///{settings.DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)

# Columns added to existing tables after the first release. create_all() creates missing tables but never alters an
# existing table, so a database built by an earlier version receives these columns at startup.
ADDED_COLUMNS = {
    "detections": [("firms_type", "INTEGER")],
    "incidents": [("reason_codes_json", "TEXT"), ("policy_version", "VARCHAR(64)"), ("details_json", "TEXT")],
}


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns(bind=None) -> List[str]:
    """Add the ADDED_COLUMNS that existing tables lack; returns "table.column" for every column added."""
    added = []
    with (bind if bind is not None else engine).begin() as connection:
        for table, columns in ADDED_COLUMNS.items():
            existing = {row[1] for row in connection.exec_driver_sql(f'PRAGMA table_info("{table}")')}
            if not existing:
                continue  # the table does not exist yet; create_all makes it with every column
            for name, ddl in columns:
                if name not in existing:
                    connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN {name} {ddl}')
                    added.append(f"{table}.{name}")
    return added


def init_db() -> None:
    from . import models  # noqa: F401  (registers the tables)

    Base.metadata.create_all(bind=engine)
    add_missing_columns()

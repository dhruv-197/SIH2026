"""Databases built by an earlier version gain the columns added since, at startup."""
import sqlite3
from contextlib import closing

from sqlalchemy import create_engine

from app.db.database import add_missing_columns


def test_an_older_database_gains_the_new_columns_once(tmp_path):
    path = tmp_path / "older.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE incidents (id INTEGER PRIMARY KEY, title TEXT)")
    connection.execute("CREATE TABLE detections (id INTEGER PRIMARY KEY, frp REAL)")
    connection.commit()
    connection.close()
    engine = create_engine(f"sqlite:///{path}")
    try:
        added = add_missing_columns(engine)
        assert set(added) == {"detections.firms_type", "incidents.reason_codes_json", "incidents.policy_version", "incidents.details_json"}
        assert add_missing_columns(engine) == []
    finally:
        engine.dispose()
    with closing(sqlite3.connect(path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(incidents)")}
    assert {"title", "reason_codes_json", "policy_version", "details_json"} <= columns

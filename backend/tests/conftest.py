"""Test configuration: an isolated temporary database, no network access and no background jobs.

Environment variables must be set before any app module is imported, which is why this runs at
conftest import time.
"""
import os
import shutil
import sys
import tempfile

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

_TMP_DIR = tempfile.mkdtemp(prefix="geothermal-tests-")
os.environ["GEOTHERMAL_DB_PATH"] = os.path.join(_TMP_DIR, "test.db")
os.environ["GEOTHERMAL_OFFLINE"] = "1"
os.environ["GEOTHERMAL_DISABLE_BACKGROUND_JOBS"] = "1"
os.environ["JWT_SECRET_KEY"] = "pytest-only-secret-key-not-used-anywhere-else-0001"
os.environ["ANALYST_PASSWORD"] = "analyst-test"
os.environ["COMMANDER_PASSWORD"] = "commander-test"


def pytest_sessionfinish(session, exitstatus):
    try:
        from app.db.database import engine

        engine.dispose()
    except Exception:
        pass
    shutil.rmtree(_TMP_DIR, ignore_errors=True)

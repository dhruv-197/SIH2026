from datetime import datetime, timedelta, timezone

from app.scheduler import next_sync_at


def test_stale_sync_is_due_immediately():
    now = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)
    last = now - timedelta(hours=5)
    assert next_sync_at(last, 180, now) == now + timedelta(seconds=5)


def test_fresh_sync_waits_the_rest_of_the_interval():
    now = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)
    last = now - timedelta(hours=1)
    assert next_sync_at(last, 180, now) == last + timedelta(minutes=180)


def test_missing_sync_is_due_immediately():
    now = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)
    assert next_sync_at(None, 180, now) == now + timedelta(seconds=5)

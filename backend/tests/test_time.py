from datetime import datetime, timezone

from backend.app.utils.time import local_now


def test_local_now_uses_china_time():
    diff_hours = (local_now() - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() / 3600

    assert 7.9 < diff_hours < 8.1

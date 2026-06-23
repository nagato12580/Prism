from datetime import datetime
from zoneinfo import ZoneInfo

from backend.app.config import settings


def local_now() -> datetime:
    return datetime.now(ZoneInfo(settings.APP_TIMEZONE)).replace(tzinfo=None)

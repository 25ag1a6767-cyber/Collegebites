from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.config import settings


def get_college_tz(tz_name: Optional[str] = None) -> ZoneInfo:
    name = (tz_name or settings.COLLEGE_TIMEZONE or "Asia/Kolkata").strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def now_college(tz_name: Optional[str] = None) -> datetime:
    """Return current timezone-aware datetime in the configured college timezone."""
    return datetime.now(get_college_tz(tz_name))


def today_college(tz_name: Optional[str] = None) -> date:
    """Return current local calendar date in the configured college timezone."""
    return now_college(tz_name).date()

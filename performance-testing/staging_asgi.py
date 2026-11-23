import sys
from datetime import timezone
from pathlib import Path

BACKEND_DIR = Path(r"C:\Users\HP\Desktop\collegebites\backend")
sys.path.insert(0, str(BACKEND_DIR))

from app.services import event_service
from app.main import app

_orig_serialize_event = event_service._serialize_event


def _safe_tz_serialize_event(ev, **kwargs):
    if getattr(ev, "ordering_deadline", None) is not None and ev.ordering_deadline.tzinfo is None:
        ev.ordering_deadline = ev.ordering_deadline.replace(tzinfo=timezone.utc)
    if getattr(ev, "created_at", None) is not None and ev.created_at.tzinfo is None:
        ev.created_at = ev.created_at.replace(tzinfo=timezone.utc)
    return _orig_serialize_event(ev, **kwargs)


event_service._serialize_event = _safe_tz_serialize_event

__all__ = ["app"]

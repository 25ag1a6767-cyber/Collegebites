import json
import logging
import sys
from datetime import datetime, timezone

from app.core.config import settings


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    if (settings.LOG_FORMAT or "").strip().lower() == "json":
        handler.setFormatter(_JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


logger = logging.getLogger("collegebites")

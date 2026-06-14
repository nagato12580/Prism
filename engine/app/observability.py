import json
import logging
from typing import Any


logger = logging.getLogger("uvicorn.error")


def truncate_text(value: Any, limit: int = 160) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def quoted(value: Any, limit: int = 160) -> str:
    return json.dumps(truncate_text(value, limit=limit), ensure_ascii=False)

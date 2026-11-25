from __future__ import annotations

import html
import re
from datetime import datetime

from tender_scout.models import SAST

_WS = re.compile(r"\s+")
PLACEHOLDERS = {"", "n/a", "na", "none", "nil", "-", "--", "null", "not applicable", "tba"}


def now_sast() -> datetime:
    return datetime.now(SAST)


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = _WS.sub(" ", html.unescape(str(value))).strip()
    if text.lower().strip(" .") in PLACEHOLDERS:
        return None
    return text or None


def none_if_blank(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalise_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()

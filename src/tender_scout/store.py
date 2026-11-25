"""Tiny JSON state store, committed to the repo by the GitHub workflow.

eTenders returns every open tender on every run, so we don't need a database to rebuild the
list. We only need to remember, per tender: when we first saw it and when we emailed it.

  data/state.json    {uid: {"first_seen_at": iso, "notified_at": iso|null, "last_seen_at": iso}}
  data/tenders.json  the latest scored list of relevant open tenders (feeds dashboard + digest)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from tender_scout.models import Tender
from tender_scout.utils import now_sast

logger = logging.getLogger(__name__)

# Forget tenders we have not seen for this long (they closed), so state.json stays small.
FORGET_AFTER_DAYS = 120


class JsonStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.state_path = data_dir / "state.json"
        self.tenders_path = data_dir / "tenders.json"
        self.state: dict[str, dict[str, str | None]] = self._read(self.state_path, {})

    @staticmethod
    def _read(path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read %s (%s); starting fresh", path, exc)
            return default

    def apply_state(self, tenders: Iterable[Tender], *, now: datetime | None = None) -> None:
        """Stamp first_seen/notified from state, and record every tender seen in this run."""
        now = now or now_sast()
        stamp = now.isoformat(timespec="seconds")
        for tender in tenders:
            entry = self.state.setdefault(tender.uid, {"first_seen_at": stamp, "notified_at": None})
            entry["last_seen_at"] = stamp
            tender.first_seen_at = datetime.fromisoformat(entry["first_seen_at"])
            tender.notified_at = datetime.fromisoformat(entry["notified_at"]) if entry.get("notified_at") else None

    def mark_notified(self, tenders: Iterable[Tender], *, now: datetime | None = None) -> None:
        stamp = (now or now_sast()).isoformat(timespec="seconds")
        for tender in tenders:
            self.state.setdefault(tender.uid, {"first_seen_at": stamp})["notified_at"] = stamp
            tender.notified_at = datetime.fromisoformat(stamp)

    def prune(self, *, now: datetime | None = None) -> int:
        cutoff = (now or now_sast()) - timedelta(days=FORGET_AFTER_DAYS)
        stale = [uid for uid, e in self.state.items() if e.get("last_seen_at") and datetime.fromisoformat(e["last_seen_at"]) < cutoff]
        for uid in stale:
            del self.state[uid]
        return len(stale)

    def save_state(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=1, sort_keys=True), encoding="utf-8")

    def save_tenders(self, tenders: list[Tender], meta: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {"meta": meta, "tenders": [t.model_dump(mode="json") for t in tenders]}
        self.tenders_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    def load_tenders(self) -> tuple[list[Tender], dict]:
        payload = self._read(self.tenders_path, {"meta": {}, "tenders": []})
        return [Tender.model_validate(t) for t in payload.get("tenders", [])], payload.get("meta", {})

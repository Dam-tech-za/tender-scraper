"""fetch -> dedupe -> score -> persist. One broken source is logged and skipped."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from tender_scout.adapters.base import SourceAdapter
from tender_scout.adapters.registry import load_adapters
from tender_scout.config import get_settings, load_profile
from tender_scout.models import Tender
from tender_scout.scoring import score_tender
from tender_scout.store import JsonStore
from tender_scout.utils import normalise_key, now_sast

logger = logging.getLogger(__name__)

# Richer sources win when the same tender arrives twice.
SOURCE_RANK = {"etenders_portal": 0, "etenders_ocds": 1}


@dataclass
class RunSummary:
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    fetched: int = 0
    unique: int = 0
    relevant: int = 0
    new: int = 0
    by_band: dict[str, int] = field(default_factory=dict)


def _fetch(adapter: SourceAdapter, summary: RunSummary) -> list[Tender]:
    name = adapter.config.get("name", adapter.source_name)
    t0 = time.perf_counter()
    try:
        tenders = list(adapter.fetch())
        summary.sources[name] = {"ok": True, "count": len(tenders), "seconds": round(time.perf_counter() - t0, 1)}
        logger.info("%s: %s tenders in %.1fs", name, len(tenders), time.perf_counter() - t0)
        return tenders
    except Exception as exc:  # noqa: BLE001
        summary.sources[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300], "seconds": round(time.perf_counter() - t0, 1)}
        logger.error("%s failed: %s", name, exc)
        return []


def fetch_all(adapters: list[SourceAdapter], summary: RunSummary) -> list[Tender]:
    primary = [a for a in adapters if not a.is_fallback]
    fallback = [a for a in adapters if a.is_fallback]
    tenders: list[Tender] = []
    for adapter in primary:
        tenders.extend(_fetch(adapter, summary))
    if not tenders and fallback:
        logger.warning("Primary sources returned nothing; running fallback sources")
        for adapter in fallback:
            tenders.extend(_fetch(adapter, summary))
    return tenders


def dedupe(tenders: list[Tender]) -> list[Tender]:
    """Merge on eTenders id, then on (entity, tender number) for re-advertised duplicates."""
    by_uid: dict[str, Tender] = {}
    for t in sorted(tenders, key=lambda t: SOURCE_RANK.get(t.source, 9)):
        by_uid.setdefault(t.uid, t)
    by_ref: dict[tuple[str, str], Tender] = {}
    out: list[Tender] = []
    for t in by_uid.values():
        ref = (normalise_key(t.entity), normalise_key(t.tender_no))
        if not all(ref):
            out.append(t)
            continue
        kept = by_ref.get(ref)
        if kept is None:
            by_ref[ref] = t
            out.append(t)
        elif t.closing_at and (kept.closing_at is None or t.closing_at > kept.closing_at):
            # Same tender re-issued with a new closing date: keep the latest notice.
            out[out.index(kept)] = t
            by_ref[ref] = t
    return out


def _sort_key(t: Tender):
    return (-t.score, t.closing_at.timestamp() if t.closing_at else float("inf"))


def run_scrape(*, store: JsonStore | None = None, adapters: list[SourceAdapter] | None = None) -> tuple[list[Tender], RunSummary]:
    settings = get_settings()
    profile = load_profile()
    store = store or JsonStore(settings.data_dir)
    summary = RunSummary()
    now = now_sast()

    raw = fetch_all(adapters if adapters is not None else load_adapters(), summary)
    summary.fetched = len(raw)
    unique = dedupe(raw)
    summary.unique = len(unique)
    if not unique:
        raise RuntimeError(f"No tenders fetched from any source: {summary.sources}")

    relevant = [t for t in (score_tender(t, profile, now=now) for t in unique) if not t.excluded]
    relevant.sort(key=_sort_key)
    store.apply_state(relevant, now=now)
    store.prune(now=now)
    summary.relevant = len(relevant)
    summary.new = sum(1 for t in relevant if t.first_seen_at and t.first_seen_at >= now.replace(microsecond=0))
    for t in relevant:
        summary.by_band[t.band] = summary.by_band.get(t.band, 0) + 1

    meta = {
        "generated_at": now.isoformat(timespec="seconds"),
        "open_tenders_scanned": summary.unique,
        "sources": summary.sources,
        "company": (profile.get("company") or {}).get("name", "Damtech"),
        "preferred_provinces": (profile.get("geography") or {}).get("preferred_provinces") or [],
    }
    store.save_tenders(relevant, meta)
    store.save_state()
    logger.info("Scan: %s open, %s relevant, %s new, bands %s", summary.unique, summary.relevant, summary.new, summary.by_band)
    return relevant, summary

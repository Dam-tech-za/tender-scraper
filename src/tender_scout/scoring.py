"""Explainable 0-100 fit score for Damtech. Rules come from config/profile.yaml; no LLM."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from tender_scout.extract import cidb_satisfied, extract_cidb
from tender_scout.models import Tender
from tender_scout.utils import now_sast


@lru_cache(maxsize=None)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


def _service_hits(text: str, group: dict[str, Any]) -> list[str]:
    return [label for label, pattern in (group.get("patterns") or {}).items() if _compile(pattern).search(text)]


def excluded_by(text: str, profile: dict[str, Any]) -> str | None:
    for pattern in profile.get("exclude_patterns") or []:
        if _compile(pattern).search(text):
            return pattern
    return None


def band_for(score: int, bands: dict[str, int]) -> str:
    for name, floor in sorted(bands.items(), key=lambda kv: kv[1], reverse=True):
        if score >= floor:
            return name
    return "Low"


def score_tender(tender: Tender, profile: dict[str, Any], *, now: datetime | None = None) -> Tender:
    """Fill score, band, reasons and flags. Sets `excluded` for tenders that are not a fit at all."""
    now = now or now_sast()
    cfg = profile.get("scoring") or {}
    company = profile.get("company") or {}
    geo = profile.get("geography") or {}
    services = profile.get("services") or {}

    reasons: list[str] = []
    flags: list[str] = []
    score = 0

    # Match on the description only for exclusions (conditions often contain boilerplate).
    if (hit := excluded_by(tender.title, profile)) is not None:
        tender.excluded = True
        tender.reasons = [f"Excluded by pattern {hit}"]
        return tender
    supply = profile.get("supply_only") or {}
    if supply.get("pattern") and (m := _compile(supply["pattern"]).search(tender.title)):
        # Only the item being supplied counts: "supply and delivery of <ITEM> for/to/at <project>".
        item = re.split(r"\b(?:for|to|at|in|near)\b", tender.title[m.end():], maxsplit=1, flags=re.I)[0]
        if not (supply.get("keep_if") and _compile(supply["keep_if"]).search(item)):
            tender.excluded = True
            tender.reasons = ["Supply-only of materials Damtech does not supply"]
            return tender
    if tender.province and tender.province in (geo.get("excluded_provinces") or []):
        tender.excluded = True
        tender.reasons = [f"Province {tender.province} excluded"]
        return tender
    if tender.closing_at and tender.closing_at <= now:
        tender.excluded = True
        tender.reasons = ["Closing date has passed"]
        return tender

    # 1. Services: does this tender ask for what Damtech does?
    text = tender.text
    core = _service_hits(text, services.get("core") or {})
    adjacent = [h for h in _service_hits(text, services.get("adjacent") or {}) if h not in core]
    if not core and not adjacent:
        tender.excluded = True
        tender.reasons = ["No Damtech service matched"]
        return tender
    if core:
        score += int((services.get("core") or {}).get("weight", 50))
        reasons.append(f"Core service: {', '.join(core)}")
    else:
        score += int((services.get("adjacent") or {}).get("weight", 25))
        reasons.append(f"Related work: {', '.join(adjacent)}")
    extra = max(0, len(core) + len(adjacent) - 1) * int(services.get("extra_hit_points", 5))
    score += min(extra, int(services.get("extra_hit_cap", 10)))
    tender.services_matched = core + adjacent

    # Generic "repairs and maintenance" for another trade (electrical, plumbing, HVAC...).
    trades = profile.get("other_trades") or {}
    if not core:
        trade_hits = [p for p in trades.get("patterns") or [] if _compile(p).search(tender.title)]
        if trade_hits:
            score += int(trades.get("penalty", -25))
            reasons.append("Mainly another trade (electrical / plumbing / mechanical...)")

    # 2. Category
    cats = profile.get("good_categories") or {}
    category = (tender.category or "").lower()
    if category and any(m.lower() in category for m in cats.get("match") or []):
        score += int(cats.get("points", 10))
        reasons.append(f"Category: {tender.category}")

    # 3. Location
    preferred = geo.get("preferred_provinces") or []
    if tender.province in preferred:
        score += int(cfg.get("preferred_province_points", 15))
        reasons.append(f"Preferred province: {tender.province}")
    elif (tender.province or "").lower() == "national" and geo.get("national_bonus", True):
        score += int(cfg.get("national_points", 8))
        reasons.append("National tender (site may be anywhere)")

    # 4. CIDB eligibility
    tender.cidb_required = extract_cidb(tender.text)
    held = company.get("cidb_gradings") or []
    if not tender.cidb_required:
        score += int(cfg.get("no_cidb_required_points", 15))
        reasons.append("No CIDB grading mentioned in the advert")
    elif cidb_satisfied(tender.cidb_required, held):
        score += int(cfg.get("cidb_held_points", 15))
        reasons.append(f"CIDB {' / '.join(tender.cidb_required)} met")
    else:
        score += int(cfg.get("cidb_missing_penalty", -20))
        flags.append("cidb_required")
        reasons.append(f"Needs CIDB {' / '.join(tender.cidb_required)}: possible subcontract / JV lead")

    # 5. Tender type
    type_points = (profile.get("tender_type_points") or {}).get(tender.tender_type or "", 0)
    if type_points:
        score += int(type_points)
        reasons.append(f"{tender.tender_type} ({'+' if type_points > 0 else ''}{type_points})")

    # 6. Timing: a missed compulsory briefing disqualifies; very short deadlines hurt.
    if tender.briefing_compulsory and tender.briefing_at and tender.briefing_at < now:
        score += int(cfg.get("briefing_missed_penalty", -40))
        flags.append("briefing_missed")
        reasons.append(f"Compulsory briefing was on {tender.briefing_at:%d %b %H:%M}: missed")
    elif tender.briefing_compulsory:
        flags.append("briefing_compulsory")
        when = f" on {tender.briefing_at:%d %b %H:%M}" if tender.briefing_at else ""
        reasons.append(f"Compulsory briefing{when}")
    days = int(cfg.get("closing_within_days", 2))
    if tender.closing_at and tender.closing_at - now <= timedelta(days=days):
        score += int(cfg.get("closing_soon_penalty", -10))
        flags.append("closing_soon")
        reasons.append(f"Closes {tender.closing_at:%d %b %H:%M}")

    if "briefing_missed" in flags:
        # A missed compulsory briefing disqualifies the bid outright: keep it visible, rank it last.
        score = min(score, int(cfg.get("briefing_missed_cap", 20)))
    tender.score = max(0, min(100, score))
    tender.band = band_for(tender.score, cfg.get("bands") or {"Hot": 75, "Strong": 60, "Possible": 45, "Low": 0})
    tender.reasons = reasons
    tender.flags = flags
    tender.excluded = False
    return tender

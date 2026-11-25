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


WORK_SUPPLY = "Supply & deliver"
WORK_SUPPLY_INSTALL = "Supply & install"
WORK_WORKS = "Works / services"


def classify_work_type(title: str, profile: dict[str, Any]) -> str:
    cfg = profile.get("work_type") or {}
    supply = cfg.get("supply") and _compile(cfg["supply"]).search(title)
    if not supply:
        return WORK_WORKS
    if cfg.get("works_override") and _compile(cfg["works_override"]).search(title):
        return WORK_WORKS
    # Only the order itself counts, not the project it is for:
    # "supply and delivery of sand FOR the X dam rehabilitation project, DWS Construction South".
    order = re.split(r"\b(?:for|to|at|near|in)\b", title[supply.start():], maxsplit=1, flags=re.I)[0]
    if cfg.get("install") and _compile(cfg["install"]).search(order):
        return WORK_SUPPLY_INSTALL
    return WORK_SUPPLY


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
    if tender.province and tender.province in (geo.get("excluded_provinces") or []):
        tender.excluded = True
        tender.reasons = [f"Province {tender.province} excluded"]
        return tender
    if tender.closing_at and tender.closing_at <= now:
        tender.excluded = True
        tender.reasons = ["Closing date has passed"]
        return tender

    # 1. Work type, then services: does this tender ask for something Damtech does or supplies?
    tender.work_type = classify_work_type(tender.title, profile)
    is_supply = tender.work_type in (WORK_SUPPLY, WORK_SUPPLY_INSTALL)
    best_weight, best_group, matched = None, None, []
    for name, group in services.items():
        if not isinstance(group, dict) or not int(group.get("weight", 0)):
            continue
        if group.get("requires_supply") and not is_supply:
            continue
        if tender.work_type in (group.get("skip_for_work_types") or []):
            continue
        haystack = tender.title if group.get("match_on") == "title" else tender.text
        hits = [h for h in _service_hits(haystack, group) if h not in matched]
        if not hits:
            continue
        matched.extend(hits)
        if best_weight is None or int(group["weight"]) > best_weight:
            best_weight, best_group = int(group["weight"]), (name, group)
        reasons.append(f"{group.get('label', name)}: {', '.join(hits)}")
    if best_group is None:
        tender.excluded = True
        tender.reasons = ["No Damtech service or product matched"]
        return tender
    score += best_weight
    extra = max(0, len(matched) - 1) * int(services.get("extra_hit_points", 5))
    score += min(extra, int(services.get("extra_hit_cap", 10)))
    tender.services_matched = matched
    tender.match_group = best_group[1].get("label", best_group[0])

    # Generic "repairs and maintenance" for another trade (electrical, plumbing, HVAC...).
    trades = profile.get("other_trades") or {}
    if best_group[1].get("trade_penalty"):
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

    # 4. CIDB eligibility. Supply & deliver contracts are not construction works: no grading needed.
    tender.cidb_required = extract_cidb(tender.text)
    held = company.get("cidb_gradings") or []
    if tender.work_type == WORK_SUPPLY:
        score += int(cfg.get("supply_only_points", 15))
        reasons.append("Supply & deliver: no CIDB grading needed")
        if tender.cidb_required:
            reasons.append(f"Advert mentions CIDB {' / '.join(tender.cidb_required)}: check the documents")
    elif not tender.cidb_required:
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

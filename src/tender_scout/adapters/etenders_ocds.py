"""National Treasury OCDS open-data API (ocds-api.etenders.gov.za). Fallback source.

Same tenders as the portal (OCDS tender.id == portal id, so they dedupe), but no province or
briefing session. Some individual records make the API answer HTTP 500 for the whole page, so we
use small pages and, when a page fails, fetch that block again one record at a time and skip only
the broken records.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Iterable

import httpx

from tender_scout.adapters.base import SourceAdapter
from tender_scout.adapters.etenders_portal import OPPORTUNITIES_URL, parse_sast
from tender_scout.http import HttpClient
from tender_scout.models import Document, Tender
from tender_scout.utils import clean_text, none_if_blank, now_sast

logger = logging.getLogger(__name__)

API_URL = "https://ocds-api.etenders.gov.za/api/OCDSReleases"


class ETendersOcdsAdapter(SourceAdapter):
    source_name = "etenders_ocds"

    def fetch(self) -> Iterable[Tender]:
        lookback = int(self.config.get("lookback_days", 30))
        page_size = int(self.config.get("page_size", 10))
        budget = int(self.config.get("max_requests", 800))
        today = now_sast().date()
        window = {"dateFrom": (today - timedelta(days=lookback)).isoformat(), "dateTo": (today + timedelta(days=1)).isoformat()}
        now = now_sast()
        requests = 0
        with HttpClient(
            allowed_hosts={"ocds-api.etenders.gov.za"},
            timeout=float(self.config.get("timeout_seconds", 60)),
            retries=0,  # a 500 here is a broken record, not a blip: retrying never helps
            delay=float(self.config.get("request_delay_seconds", 0.3)),
        ) as client:

            def page(number: int, size: int) -> list[dict[str, Any]] | None:
                nonlocal requests
                requests += 1
                try:
                    data = client.get_json(API_URL, params={"PageNumber": number, "PageSize": size, **window})
                    return data.get("releases") or []
                except (httpx.HTTPError, ValueError) as exc:
                    logger.debug("OCDS page %s/%s failed: %s", number, size, exc)
                    return None

            number = 1
            while requests < budget:
                releases = page(number, page_size)
                reached_end = releases is not None and len(releases) < page_size
                if releases is None:
                    # Re-fetch this block one record at a time; skip only the broken ones.
                    releases = []
                    first = (number - 1) * page_size + 1
                    for single in range(first, first + page_size):
                        if requests >= budget:
                            break
                        got = page(single, 1)
                        if got == []:  # a clean empty answer: past the last record
                            reached_end = True
                            break
                        releases.extend(got or [])
                for release in releases:
                    tender = self.parse(release)
                    if tender and (tender.closing_at is None or tender.closing_at > now):
                        yield tender
                if reached_end:
                    break
                number += 1
            if requests >= budget:
                logger.warning("OCDS request budget (%s) reached; results may be incomplete", budget)

    def parse(self, release: dict[str, Any]) -> Tender | None:
        t = release.get("tender") or {}
        tid = str(t.get("id") or "").strip()
        if not tid:
            return None
        entity = (t.get("procuringEntity") or {}).get("name") or (release.get("buyer") or {}).get("name")
        docs = [Document(name=d.get("title") or "document", url=d["url"]) for d in (t.get("documents") or []) if d.get("url")]
        categories = [t.get("mainProcurementCategory") or "", *(t.get("additionalProcurementCategories") or [])]
        period = t.get("tenderPeriod") or {}
        return Tender(
            uid=f"etenders:{tid}",
            source=self.source_name,
            source_id=tid,
            tender_no=none_if_blank(t.get("title")),
            title=clean_text(t.get("description")) or (t.get("title") or "Tender"),
            entity=none_if_blank(entity),
            province=None,
            category=none_if_blank(", ".join(c for c in categories if c)),
            tender_type=none_if_blank(t.get("procurementMethodDetails")),
            published_at=parse_sast(period.get("startDate")),
            closing_at=parse_sast(period.get("endDate")),
            documents=docs,
            url=OPPORTUNITIES_URL,
        )

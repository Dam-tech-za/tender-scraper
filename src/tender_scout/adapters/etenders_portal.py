"""National Treasury eTenders portal: the JSON feed behind www.etenders.gov.za "Tender Opportunities".

One request returns every currently advertised tender with province, category, briefing session,
contact person and documents. status=1 means "currently advertised".
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import quote

from tender_scout.adapters.base import SourceAdapter
from tender_scout.http import HttpClient
from tender_scout.models import SAST, Document, Tender
from tender_scout.utils import clean_text, none_if_blank

logger = logging.getLogger(__name__)

BASE = "https://www.etenders.gov.za"
LIST_URL = f"{BASE}/Home/PaginatedTenderOpportunities"
OPPORTUNITIES_URL = f"{BASE}/Home/opportunities?id=1"


def document_url(doc_id: str, extension: str | None, file_name: str) -> str:
    ext = extension or ""
    return f"{BASE}/home/Download?blobName={doc_id}{ext}&downloadedFileName={quote(file_name)}"


def parse_sast(value: str | None) -> datetime | None:
    """Portal times are South African local time without an offset."""
    if not value or value.startswith("0001-"):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=SAST) if dt.tzinfo is None else dt.astimezone(SAST)


class ETendersPortalAdapter(SourceAdapter):
    source_name = "etenders_portal"

    def fetch(self) -> Iterable[Tender]:
        page_size = int(self.config.get("page_size", 1000))
        with HttpClient(
            allowed_hosts={"www.etenders.gov.za"},
            timeout=float(self.config.get("timeout_seconds", 60)),
            retries=int(self.config.get("retries", 2)),
            delay=float(self.config.get("request_delay_seconds", 0.5)),
        ) as client:
            start = 0
            total: int | None = None
            draw = 1
            while total is None or start < total:
                payload = client.get_json(
                    LIST_URL,
                    params={"draw": draw, "start": start, "length": page_size, "status": 1},
                )
                rows = payload.get("data") or []
                total = int(payload.get("recordsTotal") or 0)
                logger.info("eTenders portal: rows %s-%s of %s", start, start + len(rows), total)
                for row in rows:
                    try:
                        yield self.parse(row)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("eTenders row %s skipped: %s", row.get("id"), exc)
                if not rows:
                    break
                start += len(rows)
                draw += 1

    def parse(self, row: dict[str, Any]) -> Tender:
        docs = [
            Document(name=d.get("fileName") or "document", url=document_url(d["supportDocumentID"], d.get("extension"), d.get("fileName") or "document"))
            for d in (row.get("supportDocument") or [])
            if d.get("supportDocumentID") and d.get("active", True)
        ]
        tid = str(row["id"])
        return Tender(
            uid=f"etenders:{tid}",
            source=self.source_name,
            source_id=tid,
            tender_no=none_if_blank(row.get("tender_No")),
            title=clean_text(row.get("description")) or (row.get("tender_No") or "Tender"),
            entity=none_if_blank(row.get("department") or row.get("organ_of_State")),
            province=none_if_blank(row.get("province")),
            category=none_if_blank(row.get("category")),
            tender_type=none_if_blank(row.get("type")),
            conditions=clean_text(row.get("conditions")),
            delivery_location=clean_text(row.get("delivery")),
            published_at=parse_sast(row.get("date_Published")),
            closing_at=parse_sast(row.get("closing_Date")),
            briefing_session=bool(row.get("briefingSession")),
            briefing_compulsory=bool(row.get("briefingCompulsory")),
            briefing_at=parse_sast(row.get("compulsory_briefing_session")),
            briefing_venue=clean_text(row.get("briefingVenue")),
            contact_person=none_if_blank(row.get("contactPerson")),
            contact_email=none_if_blank(row.get("email")),
            contact_phone=none_if_blank(row.get("telephone")),
            e_submission=bool(row.get("eSubmission")),
            documents=docs,
            url=OPPORTUNITIES_URL,
        )

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tender_scout.config import load_profile
from tender_scout.models import SAST, Tender

NOW = datetime(2026, 11, 25, 9, 0, tzinfo=SAST)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def profile() -> dict:
    return load_profile()


def portal_row(**overrides) -> dict:
    """Synthetic row shaped like www.etenders.gov.za /Home/PaginatedTenderOpportunities."""
    row = {
        "id": 900001,
        "tender_No": "RFQ-TEST-001",
        "description": "Waterproofing of concrete roof at municipal offices",
        "category": "Construction",
        "type": "Request for Quotation",
        "organ_of_State": "Test Municipality",
        "department": "Test Municipality",
        "province": "Gauteng",
        "closing_Date": "2026-12-10T11:00:00",
        "date_Published": "2026-11-24T00:00:00",
        "compulsory_briefing_session": None,
        "briefingVenue": None,
        "briefingSession": False,
        "briefingCompulsory": False,
        "conditions": "N/A",
        "contactPerson": "Test Buyer",
        "email": "buyer@example.gov.za",
        "telephone": "011-000-0000",
        "eSubmission": True,
        "delivery": "1 Main Road-Pretoria-Gauteng-0001",
        "supportDocument": [
            {"supportDocumentID": "aaaa-bbbb", "fileName": "RFQ Roof.pdf", "extension": ".pdf", "active": True}
        ],
    }
    row.update(overrides)
    return row


def make_tender(**kw) -> Tender:
    base = dict(
        uid="etenders:1",
        source="etenders_portal",
        source_id="1",
        tender_no="T1",
        title="Waterproofing of reservoir roof",
        entity="Test Municipality",
        province="Gauteng",
        category="Construction",
        tender_type="Request for Quotation",
        closing_at=NOW + timedelta(days=14),
    )
    base.update(kw)
    return Tender(**base)

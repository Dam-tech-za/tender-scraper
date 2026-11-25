import json
import os
from datetime import timedelta

import httpx
import pytest

from tender_scout import dashboard, digest
from tender_scout.adapters.etenders_ocds import ETendersOcdsAdapter
from tender_scout.adapters.etenders_portal import ETendersPortalAdapter
from tender_scout.http import HttpClient
from tender_scout.pipeline import dedupe, run_scrape
from tender_scout.store import JsonStore
from tests.conftest import NOW, make_tender, portal_row


def test_portal_parse():
    t = ETendersPortalAdapter().parse(portal_row())
    assert t.uid == "etenders:900001"
    assert t.province == "Gauteng"
    assert t.closing_at.isoformat() == "2026-12-10T11:00:00+02:00"
    assert t.conditions is None  # "N/A" placeholder dropped
    assert t.documents[0].url == "https://www.etenders.gov.za/home/Download?blobName=aaaa-bbbb.pdf&downloadedFileName=RFQ%20Roof.pdf"
    assert t.e_submission


def test_portal_paginates(monkeypatch):
    rows = [portal_row(id=i) for i in range(5)]

    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["start"])
        length = int(request.url.params["length"])
        return httpx.Response(200, json={"recordsTotal": 5, "data": rows[start : start + length]})

    mock = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("tender_scout.adapters.etenders_portal.HttpClient", lambda **kw: HttpClient(client=mock, delay=0, **{k: v for k, v in kw.items() if k != "delay"}))
    got = list(ETendersPortalAdapter({"page_size": 2}).fetch())
    assert [t.source_id for t in got] == ["0", "1", "2", "3", "4"]


def _release(i: int) -> dict:
    return {
        "tender": {
            "id": str(i),
            "title": f"T{i}",
            "description": "Waterproofing",
            "tenderPeriod": {"endDate": "2099-01-01T12:00:00Z"},
            "procuringEntity": {"name": "Entity"},
            "documents": [],
        }
    }


def test_ocds_skips_only_broken_records(monkeypatch):
    """Records 3 and 7 crash the API; every other record must still come through."""
    total, broken = 13, {3, 7}

    def handler(request: httpx.Request) -> httpx.Response:
        number = int(request.url.params["PageNumber"])
        size = int(request.url.params["PageSize"])
        ids = range((number - 1) * size + 1, min(number * size, total) + 1)
        if any(i in broken for i in ids):
            return httpx.Response(500)
        return httpx.Response(200, json={"releases": [_release(i) for i in ids]})

    mock = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "tender_scout.adapters.etenders_ocds.HttpClient",
        lambda **kw: HttpClient(client=mock, delay=0, backoff=0, retries=0, allowed_hosts=kw.get("allowed_hosts")),
    )
    got = list(ETendersOcdsAdapter({"page_size": 5}).fetch())
    assert sorted(int(t.source_id) for t in got) == [i for i in range(1, total + 1) if i not in broken]


def test_dedupe_prefers_portal_and_latest_readvert():
    portal = make_tender(uid="etenders:1", source="etenders_portal", province="Gauteng")
    ocds = make_tender(uid="etenders:1", source="etenders_ocds", province=None)
    old = make_tender(uid="etenders:2", tender_no="X-9", closing_at=NOW + timedelta(days=3))
    readvert = make_tender(uid="etenders:3", tender_no="X-9", closing_at=NOW + timedelta(days=20))
    out = dedupe([ocds, portal, old, readvert])
    assert {t.uid for t in out} == {"etenders:1", "etenders:3"}
    assert next(t for t in out if t.uid == "etenders:1").province == "Gauteng"


class FakeAdapter:
    source_name = "fake"
    is_fallback = False

    def __init__(self, tenders):
        self.tenders = tenders
        self.config = {"name": "fake"}

    def fetch(self):
        return iter(self.tenders)


def test_pipeline_state_and_digest(tmp_path):
    store = JsonStore(tmp_path)
    good = make_tender(uid="etenders:10", tender_no="A", title="Waterproofing of reservoir", closing_at=None)
    junk = make_tender(uid="etenders:11", tender_no="B", title="Catering services for year-end function", closing_at=None)
    relevant, summary = run_scrape(store=store, adapters=[FakeAdapter([good, junk])])
    assert [t.uid for t in relevant] == ["etenders:10"]
    assert summary.unique == 2 and summary.relevant == 1

    tenders, meta = store.load_tenders()
    store.apply_state(tenders)
    groups = digest.select(tenders, min_band="Possible")
    assert [t.uid for t in groups["new"]] == ["etenders:10"]

    store.mark_notified(groups["new"])
    store.save_state()
    reloaded = JsonStore(tmp_path)
    tenders, _ = reloaded.load_tenders()
    reloaded.apply_state(tenders)
    assert digest.select(tenders, min_band="Possible")["new"] == []
    assert "Damtech tenders" in digest.subject_for(groups)

    html = dashboard.render(tenders, meta)
    assert "Waterproofing of reservoir" in html and "/*__DATA__*/" not in html


def test_dashboard_escapes_script_close():
    t = make_tender(title="Evil </script><script>alert(1)</script>")
    html = dashboard.render([t], {})
    assert "</script><script>alert(1)" not in html


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("TENDER_SCOUT_LIVE"), reason="set TENDER_SCOUT_LIVE=1")
def test_live_portal_returns_open_tenders():
    tenders = list(ETendersPortalAdapter({"page_size": 1000}).fetch())
    assert len(tenders) > 500
    assert sum(1 for t in tenders if t.province) > 0.9 * len(tenders)
    json.dumps([t.model_dump(mode="json") for t in tenders[:5]])

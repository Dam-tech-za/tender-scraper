from datetime import timedelta

import pytest

from tender_scout.scoring import score_tender
from tests.conftest import make_tender


def score(profile, now, **kw):
    return score_tender(make_tender(**kw), profile, now=now)


def test_core_waterproofing_rfq_in_gauteng_is_hot(profile, now):
    t = score(profile, now, title="Waterproofing of reservoir roof at Head Office")
    assert not t.excluded
    assert t.band == "Hot"
    assert "waterproofing" in t.services_matched
    assert any("Preferred province" in r for r in t.reasons)
    assert any("No CIDB" in r for r in t.reasons)


@pytest.mark.parametrize(
    "title",
    [
        "HDPE dam lining for evaporation pond",
        "Repair and lining of leaking concrete reservoir",
        "Supply and installation of 2 x 100kl corrugated steel water tanks",
        "Torch-on waterproofing to school roofs",
        "Damp proofing and painting of clinic walls",
        "Remedial repairs to the pollution control dams",
        "MAINTENANCE AND REPAIRS OF ROBERTSON LIBRARY’S ROOF",
        "Repair of Ffennell Road Round Building (including Telemetry Wing) Roof",
    ],
)
def test_damtech_services_are_kept(profile, now, title):
    t = score(profile, now, title=title)
    assert not t.excluded, t.reasons
    assert t.services_matched


@pytest.mark.parametrize(
    "title",
    [
        "Design, layout, proofreading and printing of the annual report",
        "Leasing of 25 water tankers for three years",
        "Supply and delivery of river sand to Midmar access roads project near Midmar Dam",
        "SUPPLY AND DELIVERY OF BEDDING AND FILTER SAND FOR KWAGGASKLOOF DAM REHABILITATION PROJECT FOR DWS CONSTRUCTION SOUTH",
        "Placement of ECMO membrane oxygenation machines",
        "Supply and delivery of cartridges (stationery) for Ntabelanga Dam",
        "Security services at Die Dam resort",
        "Supply and delivery of bin liners",
        "Publication of Names of Bidders in respect of advertised bids",
        "Provision of ICT network support",
    ],
)
def test_false_positives_are_excluded(profile, now, title):
    assert score(profile, now, title=title).excluded


def test_supply_of_damtech_products_is_kept(profile, now):
    t = score(profile, now, title="Supply and delivery of HDPE liners to Farm X")
    assert not t.excluded


def test_other_trade_maintenance_is_penalised(profile, now):
    building = score(profile, now, title="Panel of contractors for building maintenance")
    electrical = score(profile, now, title="Panel of electricians for electrical building maintenance")
    assert electrical.score < building.score


def test_cidb_requirement_flags_and_penalises(profile, now):
    free = score(profile, now, title="Waterproofing of roofs")
    graded = score(profile, now, title="Waterproofing of roofs", conditions="CIDB grading 5GB or higher")
    assert graded.cidb_required == ["5GB"]
    assert "cidb_required" in graded.flags
    assert graded.score < free.score


def test_cidb_held_by_company_is_not_penalised(profile, now):
    profile = {**profile, "company": {**profile["company"], "cidb_gradings": ["5GB"]}}
    t = score(profile, now, title="Waterproofing of roofs", conditions="CIDB grading 3GB or higher")
    assert "cidb_required" not in t.flags
    assert any("met" in r for r in t.reasons)


def test_missed_compulsory_briefing(profile, now):
    t = score(
        profile,
        now,
        title="Waterproofing of roofs",
        briefing_session=True,
        briefing_compulsory=True,
        briefing_at=now - timedelta(days=1),
    )
    assert "briefing_missed" in t.flags
    assert t.band == "Low"


def test_closed_tenders_are_excluded(profile, now):
    assert score(profile, now, title="Waterproofing", closing_at=now - timedelta(hours=1)).excluded


def test_preferred_province_beats_other_province(profile, now):
    gp = score(profile, now, title="Waterproofing of roofs", province="Western Cape")
    lp = score(profile, now, title="Waterproofing of roofs", province="Limpopo")
    assert gp.score > lp.score

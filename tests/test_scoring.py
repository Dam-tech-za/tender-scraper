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
        "Placement of ECMO membrane oxygenation machines",
        "Supply and delivery of cartridges (stationery) for Ntabelanga Dam",
        "Security services at Die Dam resort",
        "Supply and delivery of bin liners",
        "Publication of Names of Bidders in respect of advertised bids",
        "Provision of ICT network support",
        "Supply and delivery of laptops for councillors",
        "Supply and delivery of a pinhole enamel tester",
        "Supply and delivery of office consumables",
        "Supply and delivery of sports clothing",
        "Manufacture and supply of hot reheat bend pipes at Matla Power Station",
        "Supply of various line hardware on an as and when required basis",
        "Appointment of a service provider to coordinate and transport the procured business equipment and working tools",
    ],
)
def test_false_positives_are_excluded(profile, now, title):
    assert score(profile, now, title=title).excluded


def test_supply_of_damtech_products_is_kept(profile, now):
    t = score(profile, now, title="Supply and delivery of HDPE liners to Farm X")
    assert not t.excluded


@pytest.mark.parametrize(
    "title,group",
    [
        ("SUPPLY AND DELIVERY OF FLINT KOTE AND SEALANT PRODUCTS FOR LOWER BERG RIVER", "Damtech product supply"),
        ("Supply and delivery of 5000L JoJo water tanks", "Damtech product supply"),
        ("Supply and delivery of waterproofing membrane rolls", "Damtech product supply"),
        ("THE APPOINTMENT OF ONE SERVICE PROVIDER TO SUPPLY AND DELIVER GENERAL BUILDING MATERIAL", "Building materials supply"),
        ("THE SUPPLY AND DELIVERY OF BULK CEMENT FOR CONCRETE WORKS IN THE NAMAKWA BULK WATER SUPPLY SCHEME", "Building materials supply"),
        ("Supply and Delivery of Galvanised Corrugated Metal Roof Sheets for a Three-Year Contract Period", "Building materials supply"),
        ("Supply of Razor Wire", "Building materials supply"),
        ("SUPPLY AND DELIVERY OF RIVER SAND TO MIDMAR ACCESS ROADS PROJECT NEAR MIDMAR DAM", "Building materials supply"),
        ("SUPPLY AND DELIVERY OF BEDDING AND FILTER SAND FOR KWAGGASKLOOF DAM REHABILITATION PROJECT FOR DWS CONSTRUCTION SOUTH", "Building materials supply"),
        ("Supply and delivery of 110mm uPVC pipes and fittings", "Building materials supply"),
        ("SUPPLY AND DELIVERY OF COLD MIX ASPHALT BAGS", "Building materials supply"),
        ("Supply and delivery of bricklaying tools", "Building materials supply"),
        ("Supply and delivery of personal protective equipment (PPE)", "General supply"),
        ("Supply and deliver cleaning material products", "General supply"),
    ],
)
def test_supply_tenders_are_matched(profile, now, title, group):
    t = score(profile, now, title=title)
    assert not t.excluded, t.reasons
    assert t.work_type == "Supply & deliver"
    assert t.match_group == group


def test_supply_only_needs_no_cidb(profile, now):
    t = score(profile, now, title="Supply and delivery of cement", conditions="CIDB grading 3GB or higher")
    assert "cidb_required" not in t.flags
    assert any("no CIDB grading needed" in r for r in t.reasons)


@pytest.mark.parametrize(
    "title,work_type",
    [
        ("Supply and delivery of building materials", "Supply & deliver"),
        ("Supply, delivery and installation of 2 x 10kl water tanks", "Supply & install"),
        ("Repairs of water supply & sewer pipe at Post Office", "Works / services"),
        ("Procurement of a contractor for construction of a new reservoir", "Works / services"),
        ("Appointment of a service provider to supply and deliver fencing material", "Supply & deliver"),
    ],
)
def test_work_type(profile, title, work_type):
    from tender_scout.scoring import classify_work_type

    assert classify_work_type(title, profile) == work_type


def test_building_supply_outranks_general_supply(profile, now):
    building = score(profile, now, title="Supply and delivery of building materials")
    ppe = score(profile, now, title="Supply and delivery of PPE")
    assert building.score > ppe.score


def test_supply_words_inside_works_titles_do_not_count(profile, now):
    # "doors" in a works tender is not a supply opportunity
    assert score(profile, now, title="Refurbishment of sliding doors at the airport").excluded


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

import pytest

from tender_scout.extract import cidb_satisfied, extract_cidb


@pytest.mark.parametrize(
    "text,expected",
    [
        ("CIDB GRADING: 7CE OR HIGHER", ["7CE"]),
        ("Tenderers should have a CIDB contractor grading designation of 4GB or higher.", ["4GB"]),
        ("CIDB GRADING 7ME OR 7CE OR HIGHER", ["7ME", "7CE"]),
        ("It is estimated that tenderers must have the CIDB contractor grading of 9 CE.", ["9CE"]),
        ("minimum CIDB Contractor grading of 4SQ or higher", ["4SQ"]),
        ("It is estimated that contractors should have a CIDB grading of 1 SL/CE or higher", ["1SL"]),
        ("Have a valid active CIDB Grade 4 or Higher.", ["4(any class)"]),
        ("Must be registered with the CIDB.", ["CIDB (grade in documents)"]),
        ("Supply of a laptop with 8 GB RAM and 2 GB graphics", []),
        ("N/A", []),
    ],
)
def test_extract_cidb(text, expected):
    assert extract_cidb(text) == expected


def test_cidb_satisfied():
    assert cidb_satisfied([], [])
    assert not cidb_satisfied(["2CE"], [])
    assert cidb_satisfied(["2CE"], ["3CE"])
    assert not cidb_satisfied(["4CE"], ["3CE"])
    assert not cidb_satisfied(["2GB"], ["3CE"])
    assert cidb_satisfied(["7ME", "2CE"], ["2CE"])  # alternatives: one is enough
    assert cidb_satisfied(["4(any class)"], ["5GB"])
    assert not cidb_satisfied(["CIDB (grade in documents)"], ["5GB"])

"""Pull structured requirements out of free-text tender conditions."""

from __future__ import annotations

import re

# CIDB classes of construction work: CE civil, GB general building, EB/EP electrical, ME mechanical,
# SA..SQ specialist classes.
_CLASS = r"(?:CE|GB|EB|EP|ME|S[A-Q])"
_GRADE = re.compile(rf"\b([1-9])\s*-?\s*({_CLASS})\b(?:\s*PE)?", re.I)
# "CIDB Grade 4 or higher" with no class given.
_GRADE_NO_CLASS = re.compile(rf"\bCIDB\b[^.;]{{0,40}}?\bgrad\w*\s*(?:of\s*)?([1-9])\b(?!\s*-?\s*{_CLASS}\b)", re.I)
_CIDB_CONTEXT = re.compile(r"\bCIDB\b|contractor\s+grading|grading\s+designation|construction\s+industry\s+development", re.I)


def extract_cidb(text: str | None) -> list[str]:
    """Return CIDB grading designations the tender asks for, e.g. ["7CE", "7EP"].

    Only looks for gradings when the text actually talks about CIDB/contractor grading, so
    things like "2 GB of storage" or "5 ME" are not picked up out of context.
    """
    if not text or not _CIDB_CONTEXT.search(text):
        return []
    found: list[str] = []
    for match in _GRADE.finditer(text):
        designation = f"{match.group(1)}{match.group(2).upper()}"
        if designation not in found:
            found.append(designation)
    if not found:
        for match in _GRADE_NO_CLASS.finditer(text):
            designation = f"{match.group(1)}(any class)"
            if designation not in found:
                found.append(designation)
    if not found:
        found.append("CIDB (grade in documents)")
    return found


def _parse(designation: str) -> tuple[int, str] | None:
    m = re.match(rf"([1-9])({_CLASS}|\(any class\))$", designation, re.I)
    return (int(m.group(1)), m.group(2).upper()) if m else None


def cidb_satisfied(required: list[str], held: list[str]) -> bool:
    """True when any one required designation is met by a held grading (same class, grade >=).

    Tenders usually list alternatives ("7ME or 7CE"), so meeting one is enough.
    """
    if not required:
        return True
    held_parsed = [p for p in (_parse(h.strip().upper()) for h in held) if p]
    if not held_parsed:
        return False
    for designation in required:
        need = _parse(designation)
        if need is None:
            continue
        grade, cls = need
        for h_grade, h_cls in held_parsed:
            if h_grade >= grade and (cls == "(ANY CLASS)" or h_cls == cls):
                return True
    return False

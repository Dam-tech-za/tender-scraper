"""Self-contained static dashboard (one HTML file, data embedded). Works offline as an email
attachment and on GitHub Pages. "Seen" and "Interested" markers live in the browser."""

from __future__ import annotations

import json
from pathlib import Path

from tender_scout.models import Tender

TEMPLATE = Path(__file__).with_name("dashboard_template.html")


def render(tenders: list[Tender], meta: dict) -> str:
    data = {"meta": meta, "tenders": [t.model_dump(mode="json") for t in tenders]}
    # Escape "</" so tender text can never close the <script> tag.
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", blob)


def write(tenders: list[Tender], meta: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(render(tenders, meta), encoding="utf-8")
    return path

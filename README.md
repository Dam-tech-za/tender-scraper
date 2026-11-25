# Tender Scout

Automated South African public tender monitoring for **Damtech**: dam lining (HDPE / PVC / torch-on),
steel water tanks and reservoirs, reservoir repair, concrete / roof / foundation waterproofing and civil works,
plus **supply & delivery** tenders for building materials and other goods Damtech can source and deliver.

Every weekday morning it scans **every open tender on the National Treasury eTenders portal** (about 2,200
at any time, from all national and provincial departments, municipalities and SOEs such as Eskom,
Transnet, SANRAL, Rand Water and Johannesburg Water). It scores each one for fit with Damtech, and emails the new
matches with a filterable dashboard attached.

It runs on GitHub Actions. No server, no database and no paid services are needed, and your computer can stay off.

## What a run does (~15 seconds)

```
eTenders portal ──► dedupe ──► score 0–100 with reasons ──► data/tenders.json ──► dashboard + email
     (fallback: eTenders OCDS API)                          data/state.json (first seen / emailed)
```

1. **Fetch:** one feed returns all currently advertised tenders with province, category, briefing
   session, contact person and document links. If the portal is down, the OCDS open-data API is used
   instead (fewer fields).
2. **Classify and filter:** every tender gets a work type (*Supply & deliver*, *Supply & install* or
   *Works / services*) and is matched against five groups in `config/profile.yaml`:

   | Group | Weight | Examples |
   | --- | --- | --- |
   | Core service | 50 | waterproofing, dam lining, reservoir repair, torch-on, damp proofing |
   | Damtech product supply | 50 | water tanks (JoJo / steel), Flintkote, sealants, bitumen, HDPE / PVC sheeting, DPC |
   | Building materials supply | 40 | general building materials, cement, ready-mix, sand, stone, aggregates, bricks, blocks, paving, rebar / mesh, roof sheets / IBR, timber, drywall, HDPE / uPVC pipes and fittings, plumbing and sanitaryware, fencing / razor wire / palisade, paint, tiles, cold-mix asphalt, hand tools, doors / windows |
   | Related work | 25 | roof repair, building maintenance, civil works, reservoir construction, fence installation |
   | General supply | 20 | PPE / protective clothing, safety signage, cleaning materials |

   Supply groups only count when the tender is actually for supply ("refurbish sliding doors" is not a
   door-supply job). For supply-only tenders the project context is ignored, so "river sand for the
   X Dam rehabilitation project" counts as a sand order, not dam work. False positives are dropped:
   "proofreading" is not roofing, "water tankers" are not water tanks, a "pinhole enamel tester" is
   not paint, and engineered power-station parts, ICT, medical and office supplies are excluded.
   Set any group's `weight: 0` to switch it off.
3. **Score:** an explainable 0–100 score with written reasons, banded **Hot / Strong / Possible / Low**:

   | Rule | Points |
   | --- | --- |
   | Best matching group (see above) | +20 to +50 |
   | Each extra item matched (max +10) | +5 |
   | Construction / civil / building / general supplies category | +10 |
   | Gauteng or Western Cape · National | +15 · +8 |
   | Supply & deliver (no CIDB needed) | +15 |
   | No CIDB grading in the advert | +15 |
   | CIDB grading required that Damtech doesn't hold | −20 (flagged as a subcontract / JV lead) |
   | Request for Quotation | +5 |
   | Mainly another trade (electrical, plumbing, HVAC...) | −25 |
   | Compulsory briefing already missed | −40, capped at 20 (you can't bid) |
   | Closes within 2 days | −10 |

4. **Email (weekdays 06:30):** new Possible-and-up tenders, plus reminders for compulsory briefings and
   closing dates in the next 3 days. Each tender is emailed once.
5. **Dashboard:** a single HTML file attached to the email (and optionally on GitHub Pages). It has search,
   province / band / **work type** / closing-date filters, "No CIDB needed", "Hide missed briefings", and per-browser
   *Seen* and *Interested* markers.

## CIDB

Damtech is not CIDB-registered yet, so the scorer:

- treats **supply & deliver** tenders as needing no CIDB grading (CIDB grades apply to construction
  works, not goods). If such an advert mentions CIDB anyway, the reason says to check the documents;
- ranks tenders that don't mention a CIDB grade highest (RFQs and smaller works usually don't);
- keeps tenders that need a grade, flagged *"Needs CIDB 7CE: possible subcontract / JV lead"*. The
  big civil and reservoir contracts often need a waterproofing or lining subcontractor;
- when you register, add your grading to `config/profile.yaml`:

  ```yaml
  company:
    cidb_gradings: ["2CE", "1GB"]
  ```

  Tenders you then qualify for get +15 instead of −20.

The grade is read from the advert's special conditions. If a tender only says "see documents", it is
shown as *"CIDB (grade in documents)"*.

## Setup

1. Push this repo to GitHub (private is fine).
2. **Settings → Actions → General → Workflow permissions:** *Read and write* (the workflow commits
   `data/` back so it remembers what it already emailed).
3. **Settings → Secrets and variables → Actions → Secrets.** Set up one email transport:
   - **Resend** (free tier, simplest): `RESEND_API_KEY`, `EMAIL_FROM` (an address on a domain verified in
     Resend, e.g. `tenders@dam-tech.co.za`), `EMAIL_TO` (comma-separated).
   - **SMTP** (e.g. Microsoft 365): `SMTP_HOST=smtp.office365.com`, `SMTP_PORT=587`, `SMTP_USER`,
     `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO`. The mailbox must have *Authenticated SMTP* enabled in
     the Microsoft 365 admin centre.

   Until email is configured the run still scrapes and builds the dashboard, and shows a warning.
4. **Actions → tenders → Run workflow** (tick *Send the email digest*) to test.
5. Optional: **GitHub Pages.** Set repository variable `ENABLE_PAGES=true`, set Settings → Pages → Source
   to *GitHub Actions*, and set variable `DASHBOARD_URL` to the Pages URL so the email links to it.
   ⚠️ On GitHub Free/Team plans **a Pages site is public even when the repo is private**. The tender data is
   public anyway, but the page would show which tenders Damtech is targeting. The emailed attachment
   needs no Pages at all.

### Schedule (SAST)

| When | What |
| --- | --- |
| Weekdays 06:30 | scrape + email digest |
| Daily 13:00 | scrape (refreshes data and dashboard) |

## Local use

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m tender_scout scrape              # fetch + score -> data/tenders.json
python -m tender_scout dashboard --out site   # -> site/index.html
python -m tender_scout digest              # dry run: prints the subject line
python -m tender_scout digest --print-html # dry run: prints the email HTML
python -m tender_scout digest --send       # sends (needs .env, see .env.example)
pytest                                     # unit tests
TENDER_SCOUT_LIVE=1 pytest -m live         # one live call to eTenders
```

## Tuning what counts as a match

Everything is in **`config/profile.yaml`**. You don't need to change any code:

- `services.core` / `services.adjacent`: regex patterns per service; add a line to catch new wording.
- `exclude_patterns`: anything matching is dropped (false-positive guards).
- `supply_only`: drops "supply and delivery of X" unless X is something Damtech supplies or installs.
- `other_trades`: penalises maintenance tenders that are really for electricians, plumbers etc.
- `geography.preferred_provinces` / `excluded_provinces`.
- `scoring`: all points, the band thresholds and which bands go into the email.

After changing patterns, run `pytest`. `tests/test_scoring.py` has real-world titles that must (and
must not) match, so add the tender that surprised you as a new case.

## Sources

| Source | Status |
| --- | --- |
| eTenders portal (www.etenders.gov.za) | **Primary.** All organs of state must advertise here. |
| eTenders OCDS API (ocds-api.etenders.gov.za) | Fallback. Some records crash the API, so it pages in 10s and skips only broken records. |
| Eskom Tender Bulletin, Transnet eTenders | Not needed: their tenders are on eTenders. |
| Municipal websites (small RFQs) | Not yet: add a per-site adapter in `src/tender_scout/adapters/` + `config/sources.yaml`. |
| Private sector (mines, farms, estates) | Out of scope: supplier portals need logins. |

To add a source, write an adapter class with a `fetch()` that yields `Tender` objects (see
`adapters/etenders_portal.py`) and register it in `config/sources.yaml`. Adapters only fetch and parse.
Scoring, dedupe, storage and email are shared.

## Project layout

```
config/profile.yaml          what Damtech does and how to score (edit this)
config/sources.yaml          which sources run
src/tender_scout/
  adapters/                  one file per source (fetch + parse only)
  extract.py                 CIDB grading extraction
  scoring.py                 rules -> score, band, reasons, flags
  pipeline.py                fetch -> dedupe -> score -> save
  store.py                   data/state.json + data/tenders.json
  digest.py                  email (Resend or SMTP)
  dashboard.py / dashboard_template.html
.github/workflows/tenders.yml
```

Architecture adapted from Job Scout (tiaandelange/Career-Python-Scraper): adapter registry,
YAML-driven explainable scoring, one broken source never stops the run.

Always confirm requirements, briefing details and closing times in the official tender documents.

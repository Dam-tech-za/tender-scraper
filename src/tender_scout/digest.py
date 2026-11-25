"""Morning email: new matching tenders, plus reminders for briefings and closings coming up.

Transport: Resend (RESEND_API_KEY) or any SMTP server (SMTP_HOST/PORT/USER/PASSWORD), e.g.
Microsoft 365 (smtp.office365.com:587) or Gmail (smtp.gmail.com:587 with an app password).
The dashboard HTML is attached so the email works even without GitHub Pages.
"""

from __future__ import annotations

import base64
import html
import logging
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

import httpx

from tender_scout.config import Settings, get_settings, load_profile
from tender_scout.models import Tender
from tender_scout.utils import now_sast

logger = logging.getLogger(__name__)

BAND_ORDER = ["Hot", "Strong", "Possible", "Low"]
BAND_COLOURS = {"Hot": "#b42318", "Strong": "#b54708", "Possible": "#175cd3", "Low": "#667085"}


def biddable(t: Tender) -> bool:
    return "briefing_missed" not in t.flags


def band_at_least(t: Tender, minimum: str) -> bool:
    return BAND_ORDER.index(t.band) <= BAND_ORDER.index(minimum) if t.band in BAND_ORDER else False


def select(tenders: list[Tender], *, min_band: str, now: datetime | None = None) -> dict[str, list[Tender]]:
    now = now or now_sast()
    soon = now + timedelta(days=3)
    good = [t for t in tenders if biddable(t) and band_at_least(t, min_band)]
    new = [t for t in good if t.notified_at is None]
    already = [t for t in good if t.notified_at is not None]
    return {
        "new": new,
        "briefings": [t for t in already if t.briefing_compulsory and t.briefing_at and now <= t.briefing_at <= soon],
        "closing": [t for t in already if t.closing_at and now <= t.closing_at <= soon],
    }


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%a %d %b %Y %H:%M") if dt else "not stated"


def _card(t: Tender) -> str:
    e = html.escape
    colour = BAND_COLOURS.get(t.band, "#667085")
    docs = " · ".join(f'<a href="{e(d.url)}">{e(d.name[:50])}</a>' for d in t.documents[:4]) or "none listed"
    briefing = ""
    if t.briefing_compulsory:
        briefing = f"<br><b>Compulsory briefing:</b> {_fmt(t.briefing_at)} — {e(t.briefing_venue or 'venue in documents')}"
    cidb = f"<br><b>CIDB:</b> {e(' / '.join(t.cidb_required))}" if t.cidb_required else ""
    contact = " · ".join(e(x) for x in (t.contact_person, t.contact_email, t.contact_phone) if x)
    return f"""
<tr><td style="padding:12px 0;border-bottom:1px solid #eaecf0;font-family:Arial,sans-serif;font-size:14px;color:#101828">
<span style="background:{colour};color:#fff;border-radius:4px;padding:2px 6px;font-size:12px">{e(t.band)} {t.score}</span>
<b style="margin-left:6px">{e(t.title[:220])}</b><br>
<span style="color:#475467">{e(t.entity or '')} · {e(t.province or '')} · {e(t.tender_no or '')} · {e(t.tender_type or '')}</span><br>
<b>Closes:</b> {_fmt(t.closing_at)}{briefing}{cidb}<br>
<span style="color:#475467">Why: {e('; '.join(t.reasons))}</span><br>
<b>Documents:</b> {docs}<br>
{f'<b>Contact:</b> {contact}' if contact else ''}
</td></tr>"""


def render_html(groups: dict[str, list[Tender]], *, total_relevant: int, dashboard_url: str = "") -> str:
    sections = []
    titles = {
        "new": "New tenders for Damtech",
        "briefings": "Compulsory briefings in the next 3 days",
        "closing": "Closing in the next 3 days",
    }
    for key in ("new", "briefings", "closing"):
        items = groups.get(key) or []
        if not items:
            continue
        rows = "".join(_card(t) for t in items)
        sections.append(
            f'<h2 style="font-family:Arial,sans-serif;font-size:17px;color:#101828;margin:24px 0 4px">{titles[key]} ({len(items)})</h2>'
            f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>'
        )
    if not sections:
        sections.append('<p style="font-family:Arial,sans-serif">No new matching tenders today.</p>')
    link = f'<p style="font-family:Arial,sans-serif"><a href="{html.escape(dashboard_url)}">Open the tender dashboard</a></p>' if dashboard_url else ""
    return f"""<!doctype html><html><body style="margin:0;padding:16px;background:#fff">
<p style="font-family:Arial,sans-serif;font-size:14px;color:#475467">{total_relevant} open tenders currently match Damtech's services. The full list is in the attached dashboard.</p>
{link}{''.join(sections)}
<p style="font-family:Arial,sans-serif;font-size:12px;color:#98a2b3;margin-top:24px">Source: National Treasury eTenders (www.etenders.gov.za). Always confirm details in the official tender documents.</p>
</body></html>"""


def subject_for(groups: dict[str, list[Tender]]) -> str:
    new = groups.get("new") or []
    hot = sum(1 for t in new if t.band == "Hot")
    parts = [f"{len(new)} new tender{'s' if len(new) != 1 else ''}"]
    if hot:
        parts.append(f"{hot} hot")
    if groups.get("briefings"):
        parts.append(f"{len(groups['briefings'])} briefing(s) soon")
    if groups.get("closing"):
        parts.append(f"{len(groups['closing'])} closing soon")
    return f"Damtech tenders: {', '.join(parts)} ({now_sast():%d %b})"


def send(subject: str, body_html: str, *, attachment: tuple[str, bytes] | None = None, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    recipients = [r.strip() for r in s.email_to.split(",") if r.strip()]
    if s.resend_api_key:
        payload: dict = {"from": s.email_from, "to": recipients, "subject": subject, "html": body_html}
        if attachment:
            payload["attachments"] = [{"filename": attachment[0], "content": base64.b64encode(attachment[1]).decode()}]
        r = httpx.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={"Authorization": f"Bearer {s.resend_api_key}"},
            timeout=30,
        )
        r.raise_for_status()
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.email_from
    msg["To"] = ", ".join(recipients)
    msg.set_content("This email is best viewed as HTML. The tender dashboard is attached.")
    msg.add_alternative(body_html, subtype="html")
    if attachment:
        msg.add_attachment(attachment[1], maintype="text", subtype="html", filename=attachment[0])
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


def min_band() -> str:
    return ((load_profile().get("scoring") or {}).get("digest_min_band")) or "Possible"

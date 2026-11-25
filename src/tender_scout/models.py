"""One tender model shared by every source. Adapters fill the source fields; scoring fills the rest."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

SAST = ZoneInfo("Africa/Johannesburg")


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str


class Tender(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Identity
    uid: str  # stable across sources: "etenders:<id>"
    source: str
    source_id: str
    tender_no: str | None = None

    # What and who
    title: str
    entity: str | None = None
    province: str | None = None
    category: str | None = None
    tender_type: str | None = None
    conditions: str | None = None
    delivery_location: str | None = None

    # When (all timezone-aware, Africa/Johannesburg)
    published_at: datetime | None = None
    closing_at: datetime | None = None
    briefing_session: bool = False
    briefing_compulsory: bool = False
    briefing_at: datetime | None = None
    briefing_venue: str | None = None

    # How to respond
    contact_person: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    e_submission: bool = False
    documents: list[Document] = Field(default_factory=list)
    url: str | None = None

    # Derived by extract/scoring
    cidb_required: list[str] = Field(default_factory=list)  # e.g. ["7CE", "7EP"]
    score: int = 0
    band: str = "Low"
    services_matched: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    excluded: bool = False

    # Tracked by the state store
    first_seen_at: datetime | None = None
    notified_at: datetime | None = None

    @property
    def text(self) -> str:
        return " ".join(p for p in (self.title, self.conditions or "") if p)

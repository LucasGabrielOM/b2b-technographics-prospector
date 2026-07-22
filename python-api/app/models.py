from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeadStatus(str, Enum):
    DISCOVERED = "discovered"
    ENRICHED = "enriched"
    DRAFTED = "drafted"
    APPROVED = "approved"
    SENT = "sent"
    SUPPRESSED = "suppressed"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(120))
    company_size: Mapped[str | None] = mapped_column(String(80))
    crm: Mapped[str | None] = mapped_column(String(80), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    lead_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    temperature: Mapped[str] = mapped_column(String(20), default="cold", index=True)
    score_reasons: Mapped[list] = mapped_column(JSON, default=list)
    contact_name: Mapped[str | None] = mapped_column(String(160))
    contact_role: Mapped[str | None] = mapped_column(String(160))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    contact_whatsapp: Mapped[str | None] = mapped_column(String(40))
    email_subject: Mapped[str | None] = mapped_column(String(240))
    email_body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default=LeadStatus.DISCOVERED.value, index=True)
    suppression_reason: Mapped[str | None] = mapped_column(String(240))
    location: Mapped[str | None] = mapped_column(String(160))
    discovery_source: Mapped[str | None] = mapped_column(String(500))
    pain_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    pain_summary: Mapped[str | None] = mapped_column(Text)
    pain_source: Mapped[str | None] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(Text)
    contact_channel: Mapped[str | None] = mapped_column(String(40))
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

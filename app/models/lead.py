"""
SQLAlchemy model for a scraped & scored lead.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("scrape_jobs.id", ondelete="CASCADE"), nullable=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    name = Column(String(200), nullable=False, default="")
    category = Column(String(200), default="")

    # ── Contact ───────────────────────────────────────────────────────────────
    phone = Column(String(50), default="")
    website = Column(String(500), default="")
    email = Column(String(200), default="")

    # ── Location ──────────────────────────────────────────────────────────────
    address = Column(String(500), default="")
    city = Column(String(100), default="")
    state = Column(String(100), default="")
    zip_code = Column(String(20), default="")

    # ── Reputation ────────────────────────────────────────────────────────────
    rating = Column(Float, default=0.0)
    reviews = Column(Integer, default=0)
    hours = Column(String(200), default="")

    # ── Source tracking ───────────────────────────────────────────────────────
    sources = Column(Text, default="")
    source_urls = Column(Text, default="")

    # ── Lead scoring ──────────────────────────────────────────────────────────
    lead_score = Column(Float, default=0.0)
    tier = Column(String(50), default="")
    score_rating = Column(Float, default=0.0)
    score_reviews = Column(Float, default=0.0)
    score_contact = Column(Float, default=0.0)
    score_sources = Column(Float, default=0.0)
    score_engagement = Column(Float, default=0.0)
    score_profile = Column(Float, default=0.0)

    # ── Meta ──────────────────────────────────────────────────────────────────
    scraped_at = Column(String(30), default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # ── Relationship ──────────────────────────────────────────────────────────
    job = relationship("ScrapeJob", back_populates="leads")

    __table_args__ = (
        Index("ix_leads_job_id", "job_id"),
        Index("ix_leads_lead_score", "lead_score"),
        Index("ix_leads_city", "city"),
        Index("ix_leads_tier", "tier"),
    )

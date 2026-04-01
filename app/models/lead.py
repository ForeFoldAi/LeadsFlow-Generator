"""
SQLAlchemy model for a scraped lead.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class Lead(Base):
    __tablename__ = "scraped_leads"

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

    # ── Source tracking ───────────────────────────────────────────────────────
    sources = Column(Text, default="")
    source_urls = Column(Text, default="")

    # ── Enrichment ────────────────────────────────────────────────────────────
    enriched_from    = Column(String(50),  default="")
    confidence_score = Column(Float,       default=0.0)

    # ── Meta ──────────────────────────────────────────────────────────────────
    scraped_at = Column(String(30), default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # ── Relationship ──────────────────────────────────────────────────────────
    job = relationship("ScrapeJob", back_populates="leads")

    __table_args__ = (
        Index("ix_scraped_leads_job_id", "job_id"),
        Index("ix_scraped_leads_city", "city"),
    )

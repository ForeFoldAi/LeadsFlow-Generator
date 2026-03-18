"""
SQLAlchemy model for a scraping job.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── Request params ────────────────────────────────────────────────────────
    keyword = Column(String(200), nullable=False)
    location = Column(String(200), nullable=False)
    sources = Column(JSON, default=list)
    max_per_source = Column(Integer, nullable=False, default=25)
    min_score = Column(Float, nullable=False, default=0.0)
    country = Column(String(100), nullable=False, default="India")

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    # pending | running | completed | failed
    status = Column(String(20), nullable=False, default="pending")
    total_found = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True, default="")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # ── Relationship ──────────────────────────────────────────────────────────
    leads = relationship("Lead", back_populates="job", cascade="all, delete-orphan", lazy="select")

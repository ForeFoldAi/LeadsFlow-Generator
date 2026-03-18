"""
Pydantic schemas for Lead responses and filters.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LeadRead(BaseModel):
    id: str
    job_id: Optional[str] = None

    # Identity
    name: str
    category: str = ""

    # Contact
    phone: str = ""
    website: str = ""
    email: str = ""

    # Location
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""

    # Reputation
    rating: float = 0.0
    reviews: int = 0
    hours: str = ""

    # Source tracking
    sources: str = ""
    source_urls: str = ""

    # Scoring
    lead_score: float = 0.0
    tier: str = ""
    score_rating: float = 0.0
    score_reviews: float = 0.0
    score_contact: float = 0.0
    score_sources: float = 0.0
    score_engagement: float = 0.0
    score_profile: float = 0.0

    # Meta
    scraped_at: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadListResponse(BaseModel):
    total: int
    leads: list[LeadRead]

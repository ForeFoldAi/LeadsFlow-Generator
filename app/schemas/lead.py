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

    # Source tracking
    sources: str = ""
    source_urls: str = ""

    # Meta
    scraped_at: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadListResponse(BaseModel):
    total: int
    leads: list[LeadRead]

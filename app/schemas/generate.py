"""
Pydantic schemas for the no-DB generate/download flow.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


ALL_SOURCES = ["google", "yelp", "yellowpages", "bbb",
               "linkedin", "facebook", "instagram", "twitter", "apollo"]


class GenerateRequest(BaseModel):
    sector: str = Field(..., examples=["plumbers"], description="Business sector / search keyword")
    city: str = Field(..., examples=["Mumbai"], description="Target city")
    country: str = Field(default="India", description="Target country")

    sources: Optional[List[str]] = Field(
        default=None,
        examples=[["google", "yelp"]],
        description=(
            "Sources to scrape. Leave null for defaults (google, yelp, yellowpages, bbb). "
            "Valid: google yelp yellowpages bbb linkedin facebook instagram twitter apollo"
        ),
    )
    max_per_source: int = Field(default=25, ge=1, le=100, description="Max results per source")
    delay: float = Field(default=1.5, ge=0.5, le=10.0, description="Seconds between requests")
    min_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Minimum lead score (0–100)")
    headless: bool = Field(default=True, description="Run browser in headless mode")


class LeadSummary(BaseModel):
    name: str
    phone: str
    email: str
    city: str
    category: str
    lead_score: float
    tier: str
    sources: str
    website: str
    rating: float
    reviews: int


class GenerateResponse(BaseModel):
    session_id: str
    status: str                          # pending | running | completed | failed
    sector: str
    city: str
    country: str
    total: int
    leads: List[LeadSummary]
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    download_csv: str
    download_excel: str

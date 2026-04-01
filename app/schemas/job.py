"""
Pydantic schemas for ScrapeJob requests and responses.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScrapeRequest(BaseModel):
    """Body for POST /api/v1/scrape"""

    keyword: str = Field(..., examples=["plumbers"], description="Search keyword, e.g. 'plumbers'")
    location: str = Field(..., examples=["Austin, TX"], description="City/region, e.g. 'Austin, TX'")
    user_id: Optional[str] = Field(default=None, description="User ID for per-user duplicate checking")

    sources: Optional[List[str]] = Field(
        default=None,
        examples=[["google", "yelp"]],
        description=(
            "Explicit source list. Leave null to use defaults. "
            "Valid: google yelp yellowpages bbb linkedin facebook instagram twitter apollo"
        ),
    )
    include_social: bool = Field(
        default=False,
        description="Append social sources: linkedin facebook instagram twitter",
    )
    include_apis: bool = Field(
        default=False,
        description="Append API sources: apollo (requires APOLLO_API_KEY in .env)",
    )

    max_per_source: int = Field(default=25, ge=1, le=100, description="Max results per source")
    min_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Minimum lead score (0–100)")
    country: str = Field(default="India", description="Country for LeadsFlow export")
    headless: bool = Field(default=True, description="Run browser in headless mode")
    delay: float = Field(default=1.5, ge=0.5, le=10.0, description="Seconds between requests")


class JobRead(BaseModel):
    id: str
    keyword: str
    location: str
    sources: List[str]
    status: JobStatus
    max_per_source: int
    min_score: float
    country: str
    user_id: Optional[str] = None
    total_found: int
    duplicate_count: int = 0
    error_message: Optional[str] = ""
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

"""
Shared Lead dataclass used across all scrapers.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Lead:
    # ── Identity ──────────────────────────────────────────
    name: str = ""
    category: str = ""

    # ── Contact ───────────────────────────────────────────
    phone: str = ""
    website: str = ""
    email: str = ""

    # ── Location ──────────────────────────────────────────
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""

    # ── Reputation (kept for merge logic, not displayed) ──
    rating: float = 0.0
    reviews: int = 0
    hours: str = ""

    # ── Source tracking ───────────────────────────────────
    sources: str = ""          # comma-separated list of sources found in
    source_urls: str = ""      # comma-separated URLs

    # ── Enrichment ────────────────────────────────────────
    enriched_from:    str   = ""    # e.g. "Google Maps"
    confidence_score: float = 0.0  # 0.0–1.0 match confidence from enrichment

    # ── Meta ──────────────────────────────────────────────
    scraped_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def source_list(self) -> list[str]:
        return [s.strip() for s in self.sources.split(",") if s.strip()]

    def add_source(self, source: str, url: str = ""):
        existing = self.source_list
        if source not in existing:
            existing.append(source)
            self.sources = ", ".join(existing)
        urls = [u.strip() for u in self.source_urls.split(",") if u.strip()]
        if url and url not in urls:
            urls.append(url)
            self.source_urls = ", ".join(urls)

    def merge(self, other: "Lead"):
        """Fill in missing fields from another lead (same business, different source)."""
        for attr in ["phone", "website", "email", "address", "city",
                     "state", "zip_code", "hours", "category"]:
            if not getattr(self, attr) and getattr(other, attr):
                setattr(self, attr, getattr(other, attr))
        # Take higher rating/reviews if both have data (used internally for merge only)
        if other.rating and (not self.rating or other.rating > self.rating):
            self.rating = other.rating
        if other.reviews > self.reviews:
            self.reviews = other.reviews
        # Merge sources
        for src, url in zip(other.source_list, other.source_urls.split(",")):
            self.add_source(src, url.strip())

from __future__ import annotations
"""
Lead Scoring & Ranking — DISABLED
All leads are returned as-is, in scrape order.
Scoring, tier, and rating logic has been removed.
"""

from app.models.lead_dataclass import Lead


def score_lead(lead: Lead) -> Lead:
    """No-op: scoring removed."""
    return lead


def rank_leads(leads: list[Lead], min_score: float = 0.0) -> list[Lead]:
    """Return leads in scrape order (scoring/ranking removed)."""
    return leads


def print_scorecard(lead: Lead):
    """No-op: scorecard removed."""
    pass

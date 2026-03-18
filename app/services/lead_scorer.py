from __future__ import annotations
"""
Lead Scoring & Ranking Model
=============================

Composite score (0–100) built from 6 weighted dimensions:

  Dimension            Weight   What it measures
  ─────────────────────────────────────────────────────────────────────
  Rating Quality         25 pts  Star rating (penalises <3.5, rewards >4.5)
  Review Authority       20 pts  Log-scaled review count (social proof volume)
  Contact Richness       20 pts  Phone + website + email + address completeness
  Source Credibility     15 pts  Multi-source presence & per-source trust weight
  Engagement Score       10 pts  rating × sqrt(reviews) — popularity signal
  Profile Completeness   10 pts  hours, category, city, zip, name quality
  ─────────────────────────────────────────────────────────────────────
  TOTAL                 100 pts

Tier thresholds:
  85–100  🏆 Hot Lead
  70–84   🔥 Strong Lead
  55–69   ✅ Good Lead
  40–54   👀 Moderate Lead
   0–39   ❄️ Weak Lead
"""

import math
from app.models.lead_dataclass import Lead

# ── Source trust weights (0–1) ────────────────────────────────────────────────
SOURCE_WEIGHTS = {
    "Google Maps":   1.00,   # highest trust — verified by Google
    "BBB":           0.95,   # verified/accredited businesses
    "Yelp":          0.85,   # strong community moderation
    "Yellow Pages":  0.75,   # established directory
    "LinkedIn":      0.80,   # professional profile quality
    "Houzz":         0.80,   # verified contractors
    "Angi":          0.78,
    "Thumbtack":     0.70,
    "Healthgrades":  0.82,
    "Avvo":          0.82,
    "TripAdvisor":   0.75,
    "Foursquare":    0.65,
    "Facebook":      0.60,
}
DEFAULT_WEIGHT = 0.60


def _source_trust(sources: list[str]) -> float:
    """Average trust weight across all sources a lead appears in."""
    if not sources:
        return DEFAULT_WEIGHT
    weights = [SOURCE_WEIGHTS.get(s, DEFAULT_WEIGHT) for s in sources]
    return sum(weights) / len(weights)


def score_lead(lead: Lead) -> Lead:
    """
    Compute all sub-scores and the composite lead_score.
    Mutates and returns the lead for convenience.
    """

    # ── 1. Rating Quality (0–25) ─────────────────────────────────────────────
    r = lead.rating
    if r <= 0:
        rating_score = 0.0
    elif r < 3.0:
        rating_score = (r / 3.0) * 5          # heavily penalised
    elif r < 3.5:
        rating_score = 5 + (r - 3.0) / 0.5 * 5   # 5–10 pts
    elif r < 4.0:
        rating_score = 10 + (r - 3.5) / 0.5 * 7  # 10–17 pts
    elif r < 4.5:
        rating_score = 17 + (r - 4.0) / 0.5 * 5  # 17–22 pts
    else:
        rating_score = 22 + (r - 4.5) / 0.5 * 3  # 22–25 pts
    rating_score = min(25.0, max(0.0, rating_score))

    # ── 2. Review Authority (0–20) ───────────────────────────────────────────
    # log10 scale: 1→0, 10→6.7, 50→11.4, 100→13.3, 500→17.8, 1000+→20
    rev = max(0, lead.reviews)
    if rev == 0:
        review_score = 0.0
    else:
        review_score = min(20.0, (math.log10(rev + 1) / math.log10(1001)) * 20)

    # ── 3. Contact Richness (0–20) ───────────────────────────────────────────
    contact_score = 0.0
    if lead.phone:    contact_score += 8.0
    if lead.website:  contact_score += 7.0
    if lead.address:  contact_score += 3.0
    if lead.email:    contact_score += 2.0

    # ── 4. Source Credibility (0–15) ─────────────────────────────────────────
    src_list = lead.source_list
    trust = _source_trust(src_list)
    multi_bonus = min(5.0, (len(src_list) - 1) * 2.5)   # +2.5 per extra source, cap 5
    source_score = min(15.0, trust * 10 + multi_bonus)

    # ── 5. Engagement Score (0–10) ───────────────────────────────────────────
    # rating × sqrt(reviews) normalised; ceiling at rating=5, reviews=500
    raw_eng = (lead.rating * math.sqrt(rev)) if lead.rating and rev else 0
    max_eng  = 5.0 * math.sqrt(500)
    engagement_score = min(10.0, (raw_eng / max_eng) * 10)

    # ── 6. Profile Completeness (0–10) ───────────────────────────────────────
    profile_score = 0.0
    if lead.name:      profile_score += 2.0
    if lead.category:  profile_score += 2.0
    if lead.city:      profile_score += 2.0
    if lead.hours:     profile_score += 2.0
    if lead.zip_code:  profile_score += 1.0
    if lead.state:     profile_score += 1.0

    # ── Composite ─────────────────────────────────────────────────────────────
    composite = (
        rating_score +
        review_score +
        contact_score +
        source_score +
        engagement_score +
        profile_score
    )
    composite = round(min(100.0, max(0.0, composite)), 1)

    # ── Tier ─────────────────────────────────────────────────────────────────
    if composite >= 85:
        tier = "🏆 Hot"
    elif composite >= 70:
        tier = "🔥 Strong"
    elif composite >= 55:
        tier = "✅ Good"
    elif composite >= 40:
        tier = "👀 Moderate"
    else:
        tier = "❄️ Weak"

    # Write back
    lead.lead_score       = composite
    lead.tier             = tier
    lead.score_rating     = round(rating_score, 1)
    lead.score_reviews    = round(review_score, 1)
    lead.score_contact    = round(contact_score, 1)
    lead.score_sources    = round(source_score, 1)
    lead.score_engagement = round(engagement_score, 1)
    lead.score_profile    = round(profile_score, 1)

    return lead


def rank_leads(leads: list[Lead], min_score: float = 0.0) -> list[Lead]:
    """Score all leads, filter by min_score, sort descending by score."""
    scored = [score_lead(lead) for lead in leads]
    filtered = [l for l in scored if l.lead_score >= min_score]
    return sorted(filtered, key=lambda l: l.lead_score, reverse=True)


def print_scorecard(lead: Lead):
    """Pretty-print the full scoring breakdown for one lead."""
    bar = lambda v, m: "█" * int(v / m * 20) + "░" * (20 - int(v / m * 20))
    print(f"""
  ┌─────────────────────────────────────────────┐
  │  {lead.name[:43]:<43}│
  │  {lead.tier}  Score: {lead.lead_score}/100{' '*(35-len(str(lead.lead_score)))}│
  ├─────────────────────────────────────────────┤
  │ Rating Quality    {bar(lead.score_rating,25)}  {lead.score_rating:>4}/25 │
  │ Review Authority  {bar(lead.score_reviews,20)}  {lead.score_reviews:>4}/20 │
  │ Contact Richness  {bar(lead.score_contact,20)}  {lead.score_contact:>4}/20 │
  │ Src Credibility   {bar(lead.score_sources,15)}  {lead.score_sources:>4}/15 │
  │ Engagement        {bar(lead.score_engagement,10)}  {lead.score_engagement:>4}/10 │
  │ Profile Complete  {bar(lead.score_profile,10)}  {lead.score_profile:>4}/10 │
  └─────────────────────────────────────────────┘""")

from __future__ import annotations
"""
Apollo.io API Scraper
=====================
Uses Apollo.io's People Search and Organization Search APIs.

Endpoints (confirmed correct):
  People search : POST https://api.apollo.io/api/v1/mixed_people/api_search
  Org search    : POST https://api.apollo.io/api/v1/mixed_companies/api_search

Setup:
  1. Go to https://developer.apollo.io/#/keys
  2. Click "Create new key" → enable "Set as master key" → Create
  3. Copy key into .env file:  APOLLO_API_KEY=your_key_here
"""

import os, re, time
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from app.models.lead_dataclass import Lead

SOURCE   = "Apollo.io"
BASE_URL = "https://api.apollo.io/api/v1"   # confirmed correct base


class ApolloScraper:
    def __init__(self, delay: float = 1.2):
        self.api_key = os.getenv("APOLLO_API_KEY", "")
        self.delay   = delay

    def _headers(self) -> dict:
        return {
            "Content-Type":  "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key":     self.api_key,
        }

    def _pause(self):
        time.sleep(self.delay)

    def _post(self, endpoint: str, payload: dict) -> dict:
        """Make a POST request to Apollo API and return JSON response."""
        url  = f"{BASE_URL}/{endpoint}"
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=30)

        if resp.status_code == 401:
            raise ValueError("❌ Invalid Apollo API key. Check APOLLO_API_KEY in .env")
        if resp.status_code == 422:
            raise RuntimeError(f"❌ Apollo 422 error: {resp.text[:300]}")
        if resp.status_code == 429:
            raise RuntimeError("❌ Apollo rate limit hit. Wait a minute and retry.")
        if resp.status_code != 200:
            raise RuntimeError(f"❌ Apollo {resp.status_code}: {resp.text[:300]}")

        return resp.json()

    # ── People Search ─────────────────────────────────────────────────────────

    def _search_people(self, keyword: str, location: str,
                       page: int = 1, per_page: int = 25) -> dict:
        parts   = [p.strip() for p in location.split(",")]
        city    = parts[0]
        country = parts[-1] if len(parts) > 1 else "India"

        payload = {
            "q_keywords":             keyword,
            "person_locations":       [city, country],
            "page":                   page,
            "per_page":               per_page,
        }
        return self._post("mixed_people/api_search", payload)

    # ── Organization Search ───────────────────────────────────────────────────

    def _search_organizations(self, keyword: str, location: str,
                               page: int = 1, per_page: int = 25) -> dict:
        parts   = [p.strip() for p in location.split(",")]
        city    = parts[0]
        country = parts[-1] if len(parts) > 1 else "India"

        payload = {
            "q_organization_keyword_tags": [keyword],
            "organization_locations":      [city, country],
            "page":                        page,
            "per_page":                    per_page,
        }
        return self._post("mixed_companies/api_search", payload)

    # ── Person dict → Lead ────────────────────────────────────────────────────

    def _person_to_lead(self, person: dict) -> Optional[Lead]:
        lead  = Lead()
        pid   = person.get("id", "")
        lead.add_source(SOURCE, f"https://app.apollo.io/#/people/{pid}")

        first = (person.get("first_name") or "").strip()
        last  = (person.get("last_name")  or "").strip()
        lead.name = f"{first} {last}".strip()
        if not lead.name:
            return None

        lead.email    = person.get("email", "") or ""
        lead.category = person.get("title", "") or ""

        # Phone — check multiple fields
        phones = person.get("phone_numbers", []) or []
        for ph in phones:
            num = ph.get("sanitized_number") or ph.get("raw_number") or ""
            if num:
                lead.phone = re.sub(r"[^\d\+]", "", num)
                break
        if not lead.phone:
            lead.phone = person.get("sanitized_phone", "") or ""

        # Company / org
        org  = person.get("organization") or person.get("account") or {}
        lead.website = (org.get("website_url") or "").strip()
        lead._apollo_company = (
            org.get("name") or person.get("organization_name") or ""
        ).strip()

        # Location
        lead.city    = (person.get("city")    or org.get("city")    or "").strip()
        lead.state   = (person.get("state")   or org.get("state")   or "").strip()
        country_val  = (person.get("country") or org.get("country") or "").strip()
        lead.address = ", ".join(p for p in [lead.city, lead.state, country_val] if p)

        # Seniority as rating proxy
        seniority_map = {
            "c_suite": 5.0, "vp": 4.8, "director": 4.6,
            "manager": 4.3, "senior": 4.0, "entry":   3.5,
        }
        lead.rating  = seniority_map.get((person.get("seniority") or "").lower(), 4.0)
        lead.reviews = int(org.get("estimated_num_employees") or 0)

        return lead

    # ── Org dict → Lead ───────────────────────────────────────────────────────

    def _org_to_lead(self, org: dict) -> Optional[Lead]:
        lead = Lead()
        oid  = org.get("id", "")
        lead.add_source(SOURCE, f"https://app.apollo.io/#/companies/{oid}")

        lead.name = (org.get("name") or "").strip()
        if not lead.name:
            return None

        lead.website  = (org.get("website_url")     or "").strip()
        lead.phone    = (org.get("sanitized_phone")  or org.get("phone") or "").strip()
        lead.email    = (org.get("contact_email")    or "").strip()
        lead.category = ", ".join((org.get("keywords") or [])[:3])

        lead.city    = (org.get("city")    or "").strip()
        lead.state   = (org.get("state")   or "").strip()
        country_val  = (org.get("country") or "").strip()
        lead.address = ", ".join(p for p in [lead.city, lead.state, country_val] if p)

        lead.reviews = int(org.get("estimated_num_employees") or 0)
        lead.rating  = 4.0
        lead._apollo_company = lead.name

        return lead

    # ── Main entry point ──────────────────────────────────────────────────────

    async def scrape(self, keyword: str, location: str,
                     max_results: int = 25, headless: bool = True) -> list[Lead]:
        if not HAS_REQUESTS:
            print("  ❌  Run: pip install requests")
            return []

        if not self.api_key:
            print("  ⏭️   Apollo skipped — add APOLLO_API_KEY to .env")
            print("        Get key at: https://developer.apollo.io/#/keys")
            return []

        leads: list[Lead] = []

        # ── People search ─────────────────────────────────────────────────────
        print(f"    Apollo People Search → {keyword} in {location}")
        try:
            pages = max(1, (max_results // 25) + 1)
            for pg in range(1, pages + 1):
                data    = self._search_people(keyword, location, page=pg, per_page=25)
                people  = data.get("people") or data.get("contacts") or []
                total   = (data.get("pagination") or {}).get("total_entries", "?")
                print(f"      Page {pg}: {len(people)} people  (total available: {total})")

                for p in people:
                    lead = self._person_to_lead(p)
                    if lead:
                        leads.append(lead)
                    if len(leads) >= max_results:
                        break

                if len(leads) >= max_results or len(people) < 25:
                    break
                self._pause()

        except Exception as e:
            print(f"  ⚠️   People search error: {e}")

        # ── Org search (fill remaining slots) ─────────────────────────────────
        remaining = max_results - len(leads)
        if remaining > 0:
            print(f"    Apollo Org Search → {keyword} in {location}")
            try:
                data  = self._search_organizations(keyword, location,
                                                    per_page=min(remaining, 25))
                orgs  = data.get("organizations") or data.get("accounts") or []
                total = (data.get("pagination") or {}).get("total_entries", "?")
                print(f"      Found {len(orgs)} orgs  (total available: {total})")

                for org in orgs:
                    lead = self._org_to_lead(org)
                    if lead:
                        leads.append(lead)
                    if len(leads) >= max_results:
                        break

            except Exception as e:
                print(f"  ⚠️   Org search error: {e}")

        # Coverage summary
        has_email = sum(1 for l in leads if l.email)
        has_phone = sum(1 for l in leads if l.phone)
        print(f"    Coverage → Email: {has_email}/{len(leads)}  "
              f"Phone: {has_phone}/{len(leads)}")

        return leads

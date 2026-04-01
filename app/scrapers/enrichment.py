from __future__ import annotations
"""Lead Enrichment Pipeline — fills missing fields using Google Maps.

Workflow
────────
  Step 1  Detect leads with missing / weak fields (phone, address, website, …)
  Step 2  Build a targeted Google Maps search query per lead
  Step 3  Search Google Maps and retrieve the top-N candidate listings
  Step 4  Match the correct business via fuzzy name + location similarity
  Step 5  Extract all available data from the matched listing
  Step 6  Smart merge: only fill gaps, never overwrite valid existing data
  Step 7  Assign a confidence score (HIGH ≥ 0.75 / MEDIUM ≥ 0.45 / LOW < 0.45)
  Step 8  Deduplicate leads after enrichment (name+phone / name+website / address)
  Step 9  Run all enrichment coroutines in parallel using a browser page pool
  Step 10 Retry failed navigation; skip unreliable low-confidence matches

Performance notes
─────────────────
  - Bounded LRU query cache (512 entries) prevents redundant Maps trips
  - asyncio page pool: exactly `concurrency` browser pages open simultaneously
  - Light resource blocking for Google Maps (keeps stylesheets, drops map tiles
    + analytics) so the JS panel renders correctly
  - Leads are modified in-place; the same list is returned
"""

import asyncio
import re
import unicodedata
from collections import OrderedDict
from contextlib import asynccontextmanager
from difflib import SequenceMatcher
from typing import Optional

from app.models.lead_dataclass import Lead
from app.scrapers.base import BaseScraper

# ── Confidence thresholds ─────────────────────────────────────────────────────
_HIGH_THRESHOLD   = 0.75   # name + location are a strong match
_MEDIUM_THRESHOLD = 0.45   # acceptable; some name variation or missing location

# ── Cache ─────────────────────────────────────────────────────────────────────
_CACHE_MAX = 512

# ── Google Maps ───────────────────────────────────────────────────────────────
_MAPS_SEARCH_BASE = "https://www.google.com/maps/search/"

# Analytics / tracker domains to block even on Maps
_MAPS_BLOCK_DOMAINS = (
    "google-analytics", "googletagmanager", "doubleclick",
    "googlesyndication", "adservice.google",
)


class LeadEnrichmentPipeline(BaseScraper):
    """
    Enriches leads from Sulekha, Yellow Pages (or any source) using Google Maps.

    Usage
    ─────
        pipeline = LeadEnrichmentPipeline(concurrency=4)
        enriched_leads = await pipeline.enrich_batch(leads)

    Each lead is modified in-place.  Fields are added as:
        lead.phone, lead.address, lead.website, …
        lead.enriched_from    = "Google Maps"
        lead.confidence_score = 0.85  (example)
    """

    def __init__(
        self,
        delay:       float = 1.5,
        proxy:       Optional[str] = None,
        concurrency: int   = 4,
    ):
        super().__init__(delay=delay, proxy=proxy)
        self._concurrency = concurrency
        # Bounded LRU cache: query string → list of candidate dicts
        self._cache: OrderedDict[str, list[dict]] = OrderedDict()

    # ── Step 1: Detect missing fields ─────────────────────────────────────────

    @staticmethod
    def _needs_enrichment(lead: Lead) -> bool:
        """True when the lead is missing any high-value field."""
        return not (lead.phone and lead.address and lead.website)

    @staticmethod
    def _missing_fields(lead: Lead) -> list[str]:
        missing: list[str] = []
        if not lead.phone:   missing.append("phone")
        if not lead.email:   missing.append("email")
        if not lead.website: missing.append("website")
        if not lead.address: missing.append("address")
        if not lead.rating:  missing.append("rating")
        if not lead.reviews: missing.append("reviews")
        return missing

    # ── Step 2: Build search query ────────────────────────────────────────────

    @staticmethod
    def _build_query(lead: Lead) -> str:
        """
        Construct a targeted Google Maps query.

        Examples
        ────────
            "ABC Caterers Begumpet Hyderabad"
            "XYZ School Panjagutta Hyderabad"
            "Mad Academy Hyderabad"
        """
        parts = [lead.name.strip()]

        # Extract a meaningful area/locality from the address string.
        # Typical Indian address: "Shop 5, Begumpet, Hyderabad – 500016"
        #   → we want "Begumpet" (skip the shop/building part and the city/pin).
        if lead.address:
            _skip_prefix = re.compile(
                r"^\s*(?:\d[\d/\-]*|shop|flat|floor|plot|door|no\.?|#|[a-z]{1,2}\.)\b",
                re.IGNORECASE,
            )
            addr_parts = [p.strip() for p in lead.address.split(",") if p.strip()]
            # Drop first token if it looks like a building/shop number
            if len(addr_parts) > 1 and _skip_prefix.match(addr_parts[0]):
                addr_parts = addr_parts[1:]
            city_lower = (lead.city or "").lower()
            for part in addr_parts[:-1]:  # last part is usually city / PIN — skip
                # Don't append if it merely repeats the city name
                if part.lower() not in city_lower and city_lower not in part.lower():
                    parts.append(part)
                    break

        if lead.city:
            parts.append(lead.city.strip())

        return " ".join(p for p in parts if p)

    # ── Steps 4 + 7: Matching and confidence scoring ──────────────────────────

    @staticmethod
    def _normalize_name(s: str) -> str:
        """Lowercase, ASCII-only, strip legal suffixes and punctuation."""
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
        s = re.sub(
            r"\b(pvt|private|limited|ltd|llp|inc|co|the|and|&|a)\b\.?",
            "", s, flags=re.IGNORECASE,
        )
        return re.sub(r"[^a-z0-9 ]", "", s).strip()

    @classmethod
    def _name_similarity(cls, a: str, b: str) -> float:
        """
        SequenceMatcher similarity after normalisation.
        Boosts score when one name is fully contained within the other
        (e.g. "ABC" matching "ABC Pvt Ltd").
        """
        a_n, b_n = cls._normalize_name(a), cls._normalize_name(b)
        if not a_n or not b_n:
            return 0.0
        ratio = SequenceMatcher(None, a_n, b_n).ratio()
        if a_n in b_n or b_n in a_n:
            ratio = max(ratio, 0.80)
        return ratio

    @staticmethod
    def _location_match(lead: Lead, candidate: dict) -> float:
        """
        0.0–1.0: how well the candidate's address/city aligns with the lead's city.
        Returns 0.5 (neutral) when lead has no city — avoids penalising leads
        that were scraped without a city field.
        """
        lead_city = (lead.city or "").lower().strip()
        if not lead_city:
            return 0.5

        haystack = " ".join([
            (candidate.get("address") or ""),
            (candidate.get("city")    or ""),
        ]).lower()

        if lead_city in haystack:
            return 1.0

        # Word-level partial overlap
        lead_words = set(lead_city.split())
        hay_words  = set(haystack.split())
        overlap    = lead_words & hay_words
        return len(overlap) / len(lead_words) if lead_words else 0.0

    def _confidence_score(self, lead: Lead, candidate: dict) -> float:
        """
        Composite score:
          70% name similarity  (most important — prevents cross-business matches)
          22% location match   (filters city-level false positives)
           8% category bonus   (optional signal)
        """
        name_sim = self._name_similarity(lead.name, candidate.get("name", ""))
        loc_sim  = self._location_match(lead, candidate)

        cat_bonus = 0.0
        if lead.category and candidate.get("category"):
            lead_kws = [w for w in lead.category.lower().split() if len(w) > 3]
            cand_cat = candidate.get("category", "").lower()
            if any(kw in cand_cat for kw in lead_kws):
                cat_bonus = 0.08

        score = (name_sim * 0.70) + (loc_sim * 0.22) + cat_bonus
        return round(min(score, 1.0), 3)

    def _find_best_match(
        self, lead: Lead, candidates: list[dict]
    ) -> Optional[tuple[dict, float]]:
        """
        Return (best_candidate, confidence) when confidence ≥ MEDIUM_THRESHOLD,
        otherwise None.  LOW confidence matches are silently rejected.
        """
        best:  Optional[dict] = None
        best_score = 0.0

        for cand in candidates:
            if not cand.get("name"):
                continue
            score = self._confidence_score(lead, cand)
            self._log.debug(
                "  candidate=%r score=%.3f (lead=%r)", cand["name"], score, lead.name
            )
            if score > best_score:
                best_score = score
                best = cand

        if best and best_score >= _MEDIUM_THRESHOLD:
            tier = "HIGH" if best_score >= _HIGH_THRESHOLD else "MEDIUM"
            self._log.debug("  accepted=%r confidence=%.3f tier=%s", best["name"], best_score, tier)
            return best, best_score

        self._log.debug("  rejected: best_score=%.3f < threshold=%.2f", best_score, _MEDIUM_THRESHOLD)
        return None

    # ── Step 6: Smart merge ───────────────────────────────────────────────────

    def _merge_into_lead(self, lead: Lead, matched: dict, confidence: float) -> None:
        """
        Copy available fields from the Google Maps result into the lead.
        Existing valid data is NEVER overwritten.
        """
        _SRC = "Google Maps"

        if not lead.phone and matched.get("phone"):
            cleaned = self._clean_phone(matched["phone"])
            lead.phone = cleaned or matched["phone"]

        if not lead.address and matched.get("address"):
            lead.address = matched["address"]

        if not lead.city and matched.get("city"):
            lead.city = matched["city"]

        if not lead.state and matched.get("state"):
            lead.state = matched["state"]

        if not lead.zip_code and matched.get("zip_code"):
            lead.zip_code = matched["zip_code"]

        if not lead.website and matched.get("website"):
            lead.website = matched["website"]

        if not lead.hours and matched.get("hours"):
            lead.hours = matched["hours"]

        if not lead.category and matched.get("category"):
            lead.category = matched["category"]

        # Prefer higher rating / more reviews
        cand_rating = float(matched.get("rating") or 0)
        if cand_rating and (not lead.rating or cand_rating > lead.rating):
            lead.rating = cand_rating

        cand_reviews = int(matched.get("reviews") or 0)
        if cand_reviews > lead.reviews:
            lead.reviews = cand_reviews

        # Record enrichment metadata
        lead.add_source(_SRC, matched.get("url", ""))
        lead.enriched_from    = _SRC
        lead.confidence_score = confidence

    # ── Step 3: Google Maps resource blocking (Maps-safe) ─────────────────────

    async def _block_maps_resources(self, route) -> None:
        """
        Lighter blocking suited for Google Maps:
          - Abort fonts (never needed)
          - Abort analytics / ad trackers
          - Abort map tile images (heavy PNG/WebP tiles that don't affect panel data)
          - Keep stylesheets so the JS shell renders the panel correctly
        """
        url   = route.request.url
        rtype = route.request.resource_type

        if rtype == "font":
            await route.abort()
            return

        if any(d in url for d in _MAPS_BLOCK_DOMAINS):
            await route.abort()
            return

        # Drop satellite/road map tile images — not needed for listing panels
        if rtype == "image" and (
            "maps/vt" in url or "maps/api/staticmap" in url or "/maps/mv/?" in url
        ):
            await route.abort()
            return

        await route.continue_()

    # ── Step 3: Search Google Maps ────────────────────────────────────────────

    async def _search_google_maps(
        self, page, query: str, max_candidates: int = 3
    ) -> list[dict]:
        """
        Search Google Maps for `query`.  Returns up to `max_candidates` enriched
        business dicts.  Caches results keyed on the normalised query string.
        """
        cache_key = query.lower().strip()
        if cache_key in self._cache:
            self._log.debug("[MAPS_CACHE] hit: %r", query)
            return self._cache[cache_key]

        url = _MAPS_SEARCH_BASE + query.replace(" ", "+")
        if not await self._goto(page, url):
            return []

        await self._pause()

        # Dismiss EU/UK cookie consent banner
        try:
            btn = page.locator('button:has-text("Accept all")')
            if await btn.first.is_visible(timeout=2000):
                await btn.first.click()
        except Exception:
            pass

        candidates: list[dict] = []

        # ── Path A: multiple results in a scrollable feed ──────────────────────
        try:
            await page.wait_for_selector('div[role="feed"]', timeout=8_000)

            urls: list[str] = []
            seen: set[str]  = set()
            stalled = 0

            while len(urls) < max_candidates and stalled < 3:
                anchors = await page.query_selector_all('a[href*="/maps/place/"]')
                before  = len(urls)
                for a in anchors:
                    href = (await a.get_attribute("href")) or ""
                    m = re.match(r"(https://www\.google\.com/maps/place/[^?]+)", href)
                    if m and m.group(1) not in seen:
                        seen.add(m.group(1))
                        urls.append(m.group(1))
                        if len(urls) >= max_candidates:
                            break
                stalled = 0 if len(urls) > before else stalled + 1
                if len(urls) < max_candidates:
                    feed = await page.query_selector('div[role="feed"]')
                    if feed:
                        await feed.evaluate("el => el.scrollBy(0, 600)")
                        await asyncio.sleep(0.6)

            for u in urls:
                biz = await self._extract_maps_listing(page, u)
                if biz:
                    candidates.append(biz)

        except Exception:
            # ── Path B: Google redirected directly to a single business panel ──
            biz = await self._extract_maps_listing(page, page.url)
            if biz:
                candidates.append(biz)

        # Store in bounded LRU cache
        self._cache[cache_key] = candidates
        if len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)  # evict oldest entry

        return candidates

    # ── Step 5: Extract data from a Maps place page ───────────────────────────

    async def _extract_maps_listing(self, page, url: str) -> Optional[dict]:
        """
        Navigate to a Google Maps place URL and extract every available field.
        Uses the same CSS patterns as the standalone GoogleMapsScraper.
        Returns None if no business name is found.
        """
        try:
            if page.url != url:
                if not await self._goto(page, url):
                    return None
                await asyncio.sleep(0.8)

            info: dict = {"url": url}

            # ── Name ──────────────────────────────────────────────────────────
            el = await page.query_selector('h1.DUwDvf, h1[class*="fontHeadlineLarge"]')
            if el:
                info["name"] = (await el.inner_text()).strip()

            if not info.get("name"):
                return None   # nothing useful to extract

            # ── Category ──────────────────────────────────────────────────────
            el = await page.query_selector('button[jsaction*="category"], .DkEaL')
            if el:
                info["category"] = (await el.inner_text()).strip()

            # ── Rating ────────────────────────────────────────────────────────
            el = await page.query_selector('div.F7nice span[aria-hidden="true"]')
            if el:
                try:
                    info["rating"] = float((await el.inner_text()).strip())
                except Exception:
                    pass

            # ── Review count ──────────────────────────────────────────────────
            el = await page.query_selector('div.F7nice span[aria-label*="review"]')
            if el:
                label = (await el.get_attribute("aria-label")) or ""
                nums  = re.findall(r"[\d,]+", label)
                if nums:
                    try:
                        info["reviews"] = int(nums[0].replace(",", ""))
                    except Exception:
                        pass

            # ── Address ───────────────────────────────────────────────────────
            el = await page.query_selector('button[data-item-id="address"] .Io6YTe')
            if el:
                addr = (await el.inner_text()).strip()
                info["address"] = addr
                parts = addr.split(",")
                if len(parts) >= 2:
                    info["city"] = parts[-2].strip()
                if parts:
                    last = parts[-1].strip().split()
                    if len(last) >= 2:
                        info["state"]    = last[0]
                        info["zip_code"] = last[1]

            # ── Phone ─────────────────────────────────────────────────────────
            el = await page.query_selector('button[data-item-id*="phone"] .Io6YTe')
            if el:
                info["phone"] = (await el.inner_text()).strip()

            # ── Website ───────────────────────────────────────────────────────
            el = await page.query_selector('a[data-item-id="authority"] .Io6YTe')
            if el:
                info["website"] = (await el.inner_text()).strip()

            # ── Business hours ─────────────────────────────────────────────────
            el = await page.query_selector(
                'div[aria-label*="hour"], button[aria-label*="hour"]'
            )
            if el:
                label = (await el.get_attribute("aria-label")) or ""
                # "Open ⋅ Closes 10 pm  ⋅  …" — take the first segment
                info["hours"] = label.split("⋅")[0].strip() or label.split("·")[0].strip()

            return info

        except Exception as exc:
            self._log.debug("[MAPS_EXTRACT] error %s: %s", url, exc)
            return None

    # ── Per-lead enrichment ────────────────────────────────────────────────────

    async def _enrich_lead(self, page, lead: Lead) -> None:
        """Run the full enrichment pipeline for a single lead (Steps 1–7)."""
        query   = self._build_query(lead)
        missing = self._missing_fields(lead)

        self._log.debug(
            "[ENRICH_START] name=%r query=%r missing=%s", lead.name, query, missing
        )

        candidates = await self._search_google_maps(page, query)
        if not candidates:
            self._log.debug("[ENRICH_SKIP] no Maps results for %r", lead.name)
            return

        result = self._find_best_match(lead, candidates)
        if not result:
            self._log.debug(
                "[ENRICH_SKIP] no confident match for %r (candidates=%d)",
                lead.name, len(candidates),
            )
            return

        matched, confidence = result
        before_missing = self._missing_fields(lead)
        self._merge_into_lead(lead, matched, confidence)
        after_missing  = self._missing_fields(lead)
        filled         = [f for f in before_missing if f not in after_missing]

        self._log.info(
            "[ENRICH_DONE] name=%r confidence=%.2f filled=%s",
            lead.name, confidence, filled or "nothing new",
        )

    # ── Step 9a: Shared-browser streaming enrichment ──────────────────────────

    @asynccontextmanager
    async def stream(self, headless: bool = True):
        """
        Keep one browser + page pool open for the full scraping session.

        Usage::

            async with pipeline.stream(headless) as enrich_leads:
                task = asyncio.create_task(enrich_leads(batch))
                ...          # other work while enrichment runs
                await task   # wait before browser closes

        Yields an ``enrich_leads(leads)`` coroutine that enriches leads
        in-place using the shared page pool and returns the same list.
        The browser is closed when the context exits.
        """
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(**self._launch_kwargs(headless))
            ctx     = await browser.new_context(**self._ctx_kwargs())

            sem        = asyncio.Semaphore(self._concurrency)
            page_queue: asyncio.Queue = asyncio.Queue()
            pages: list = []

            for _ in range(self._concurrency):
                pg = await ctx.new_page()
                await pg.route("**/*", self._block_maps_resources)
                pages.append(pg)
                await page_queue.put(pg)

            async def enrich_leads(leads: list[Lead]) -> list[Lead]:
                to_enrich = [l for l in leads if self._needs_enrichment(l)]
                if not to_enrich:
                    return leads

                async def _one(lead: Lead) -> None:
                    async with sem:
                        pg = await page_queue.get()
                        try:
                            await self._enrich_lead(pg, lead)
                        except Exception as exc:
                            self._log.warning(
                                "[ENRICH_ERROR] name=%r error=%s", lead.name, exc
                            )
                        finally:
                            await page_queue.put(pg)

                await asyncio.gather(*[_one(l) for l in to_enrich])
                return leads

            try:
                yield enrich_leads
            finally:
                for pg in pages:
                    try:
                        await pg.close()
                    except Exception:
                        pass
                await browser.close()

    # ── Step 9: Parallel batch enrichment ─────────────────────────────────────

    async def enrich_batch(
        self,
        leads:    list[Lead],
        headless: bool = True,
    ) -> list[Lead]:
        """
        Enrich all leads in the list that are missing data.

        - Skips leads that already have phone + address + website.
        - Runs up to `self._concurrency` concurrent browser pages.
        - Deduplicates the final result list (Step 8).
        - Returns the enriched (and deduplicated) list.
        """
        to_enrich = [l for l in leads if self._needs_enrichment(l)]

        self._log.info(
            "[BATCH_START] total=%d to_enrich=%d", len(leads), len(to_enrich)
        )

        if not to_enrich:
            return leads

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(**self._launch_kwargs(headless))
            ctx     = await browser.new_context(**self._ctx_kwargs())

            n_pages    = min(self._concurrency, len(to_enrich))
            sem        = asyncio.Semaphore(n_pages)
            page_queue: asyncio.Queue = asyncio.Queue()
            pages      = []

            for _ in range(n_pages):
                pg = await ctx.new_page()
                await pg.route("**/*", self._block_maps_resources)
                pages.append(pg)
                await page_queue.put(pg)

            async def enrich_one(lead: Lead) -> None:
                async with sem:
                    pg = await page_queue.get()
                    try:
                        await self._enrich_lead(pg, lead)
                    except Exception as exc:
                        self._log.warning(
                            "[ENRICH_ERROR] name=%r error=%s", lead.name, exc
                        )
                    finally:
                        await page_queue.put(pg)

            await asyncio.gather(*[enrich_one(l) for l in to_enrich])

            for pg in pages:
                try:
                    await pg.close()
                except Exception:
                    pass

            await browser.close()

        self._log.info("[BATCH_DONE] enriched=%d", sum(
            1 for l in leads if l.enriched_from
        ))

        # Step 8: deduplicate the final result
        return self._deduplicate(leads)

    # ── Step 8: Post-enrichment deduplication ─────────────────────────────────

    @staticmethod
    def _deduplicate(leads: list[Lead]) -> list[Lead]:
        """
        Remove duplicates after enrichment using three composite keys
        (in descending reliability order):

          1. normalised_name + last_10_digits_of_phone
          2. normalised_name + website domain
          3. normalised_name + address prefix

        When a duplicate is found the earlier (primary-scraper) record is kept
        and the later record is merged into it via Lead.merge().
        """
        index:  dict[str, Lead] = {}
        result: list[Lead]      = []

        for lead in leads:
            keys: list[str] = []

            if lead.phone:
                keys.append(BaseScraper._dedup_key(lead.name, lead.phone))

            if lead.website:
                domain = re.sub(r"^https?://(www\.)?", "", lead.website.lower()).rstrip("/")
                n = re.sub(r"[^a-z0-9]", "", lead.name.lower())
                keys.append(f"web:{n}:{domain[:40]}")

            if lead.address:
                addr_key = re.sub(r"\s+", "", lead.address.lower())[:40]
                n = re.sub(r"[^a-z0-9]", "", lead.name.lower())
                keys.append(f"addr:{n}:{addr_key}")

            merged = False
            for k in keys:
                if k in index:
                    index[k].merge(lead)
                    merged = True
                    break

            if not merged:
                result.append(lead)
                for k in keys:
                    index[k] = lead

        return result

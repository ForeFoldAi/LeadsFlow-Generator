from __future__ import annotations
"""Yellow Pages India (yellowpages.in) scraper — v3.

The old AJAX endpoint (/helper.aspx/Search) is permanently dead.
This rewrite uses the server-side-rendered search results at:

    GET http://yellowpages.in/search/{city}/{keyword}

Listings live in  ul#MainContent_ulFList li  and are fully rendered
in the initial HTML — no JavaScript execution needed.

Architecture
────────────
  • Static HTTP fetch (requests) for the search-results pages
  • Playwright (headless) for individual business profile pages that
    need phone-reveal clicks
  • asyncio.Semaphore for bounded parallel profile fetches
  • Composite dedup key: normalised name + phone
"""

import asyncio
import functools
import random
import re
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.models.lead_dataclass import Lead
from app.scrapers.base import BaseScraper

SOURCE   = "Yellow Pages"
BASE_URL = "http://yellowpages.in"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer":         f"{BASE_URL}/",
}


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://",  adapter)
    session.mount("https://", adapter)
    session.headers.update(_HEADERS)
    return session


def _search_url(keyword: str, city: str, page: int = 1) -> str:
    """
    Build the search URL.
    e.g. keyword="wedding caterers", city="Hyderabad"
    → http://yellowpages.in/search/hyderabad/wedding-caterers
    → http://yellowpages.in/search/hyderabad/wedding-caterers/2  (page 2+)
    """
    city_slug    = re.sub(r"\s+", "-", city.strip().lower())
    keyword_slug = re.sub(r"\s+", "-", keyword.strip().lower())
    base = f"{BASE_URL}/search/{city_slug}/{keyword_slug}"
    return base if page == 1 else f"{base}/{page}"


# ─── Listing-page parsers ──────────────────────────────────────────────────────

def _parse_rating_class(html_snippet: str) -> float:
    """
    Ratings are encoded as CSS classes like  r4-5  (= 4.5) or  r3-0  (= 3.0).
    Handles both single and double quoted attributes.
    """
    m = re.search(r"""class=['"][^'"]*\brating\s+r(\d)-(\d)[^'"]*['"]""", html_snippet, re.IGNORECASE)
    if m:
        try:
            return float(f"{m.group(1)}.{m.group(2)}")
        except ValueError:
            pass
    return 0.0


def _parse_listing_block(block: str) -> Optional[dict]:
    """
    Parse one  <li>  block from  ul#MainContent_ulFList.
    Returns a dict with keys: name, url, phone, address, area, city_part,
    zip_code, rating, reviews, hours, category.

    Note: yellowpages.in uses single-quoted attributes throughout.
    All patterns handle both single and double quotes via  ['"]  groups.
    """
    info: dict = {}
    Q = r"""['"]"""  # matches either quote style

    # ── Name + URL ─────────────────────────────────────────────────────────
    # <a href='/b/...' class='eachPopularTitle hasOtherInfo'>Business Name</a>
    m = re.search(
        r"""<a\s[^>]*class=""" + Q + r"""[^'"]*eachPopularTitle[^'"]*""" + Q +
        r"""[^>]*href=""" + Q + r"""(/[^'"?#]*)""" + Q + r"""[^>]*>\s*([^<]+?)\s*</a>""",
        block, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        # Also try href-first ordering
        m = re.search(
            r"""<a\s[^>]*href=""" + Q + r"""(/[^'"?#]*)""" + Q +
            r"""[^>]*class=""" + Q + r"""[^'"]*eachPopularTitle[^'"]*""" + Q +
            r"""[^>]*>\s*([^<]+?)\s*</a>""",
            block, re.IGNORECASE | re.DOTALL,
        )
    if not m:
        return None
    info["url"]  = BASE_URL + m.group(1).strip()
    info["name"] = re.sub(r"\s+", " ", m.group(2)).strip()

    # ── Phone ──────────────────────────────────────────────────────────────
    # <a class='businessContact' href='tel:9849019955'>+91 9849019955</a>
    m_ph = re.search(r"""href=['"]tel:([+\d\s\-()/]{7,})['"]""", block, re.IGNORECASE)
    if m_ph:
        info["phone"] = m_ph.group(1).strip()

    # ── Address ────────────────────────────────────────────────────────────
    # <address class='businessArea'><strong>Safilguda</strong> Hyderabad - 500047</address>
    m_addr = re.search(
        r"""<address[^>]*class=""" + Q + r"""[^'"]*businessArea[^'"]*""" + Q + r"""[^>]*>(.*?)</address>""",
        block, re.IGNORECASE | re.DOTALL,
    )
    if m_addr:
        raw_addr = re.sub(r"<[^>]+>", " ", m_addr.group(1))
        raw_addr = re.sub(r"\s+", " ", raw_addr).strip()
        info["address"] = raw_addr

        m_area = re.search(r"<strong[^>]*>\s*([^<]+?)\s*</strong>", m_addr.group(1), re.IGNORECASE)
        if m_area:
            info["area"] = m_area.group(1).strip()

        after_strong = re.sub(
            r"<[^>]+>", " ",
            re.sub(r"<strong>.*?</strong>", "", m_addr.group(1), flags=re.DOTALL),
        )
        after_strong = re.sub(r"\s+", " ", after_strong).strip().strip("-").strip()
        if after_strong:
            pin_m = re.search(r"\b(\d{6})\b", after_strong)
            if pin_m:
                info["zip_code"] = pin_m.group(1)
            city_m = re.match(r"([A-Za-z][A-Za-z\s]+?)(?:\s*[-–]\s*\d{6}|$)", after_strong)
            if city_m:
                info["city_part"] = city_m.group(1).strip()

    # ── Rating ─────────────────────────────────────────────────────────────
    r = _parse_rating_class(block)
    if r:
        info["rating"] = r

    # ── Reviews ────────────────────────────────────────────────────────────
    # <a class='ratingCount'>5 reviews</a>
    m_rev = re.search(
        r"""class=""" + Q + r"""[^'"]*ratingCount[^'"]*""" + Q + r"""[^>]*>\s*(\d+)\s*review""",
        block, re.IGNORECASE,
    )
    if m_rev:
        info["reviews"] = int(m_rev.group(1))

    # ── Hours ──────────────────────────────────────────────────────────────
    # <div class='openNow'><strong>Open 24 Hours</strong></div>
    m_hrs = re.search(
        r"""class=""" + Q + r"""[^'"]*openNow[^'"]*""" + Q + r"""[^>]*>.*?<strong[^>]*>\s*([^<]+?)\s*</strong>""",
        block, re.IGNORECASE | re.DOTALL,
    )
    if m_hrs:
        info["hours"] = m_hrs.group(1).strip()

    # ── Category ───────────────────────────────────────────────────────────
    # <ul class='eachPopularTagsList'><li><a href='...'>Catering Services</a></li></ul>
    m_cats = re.findall(
        r"""class=""" + Q + r"""[^'"]*eachPopularTagsList[^'"]*""" + Q + r""".*?<a[^>]*>\s*([^<]+?)\s*</a>""",
        block, re.IGNORECASE | re.DOTALL,
    )
    if m_cats:
        info["category"] = ", ".join(c.strip() for c in m_cats[:3])

    return info


def _split_listings(html: str) -> list[str]:
    """
    Split the full page HTML into per-listing blocks.

    Each listing is wrapped in  <div class='eachPopular'>  (or "eachPopular").
    We split on those divs to avoid false splits from nested <li> tags inside
    category tag lists (eachPopularTagsList) within each listing.
    """
    parts = re.split(r"(?=<div[^>]*class=['\"][^'\"]*\beachPopular\b[^'\"]*['\"])", html, flags=re.IGNORECASE)
    return [p for p in parts if "eachPopularTitle" in p]


# ─── Profile page parser (static) ─────────────────────────────────────────────

def _scrape_profile_static(session: requests.Session, url: str) -> Optional[dict]:
    """
    GET a business profile page and extract extra fields that weren't
    available on the search-results page.
    """
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        src = resp.text
    except Exception:
        return None

    info: dict = {}

    # Email
    m_email = re.search(r'href="mailto:([^"@\s]{3,}@[^"@\s]{3,})"', src, re.IGNORECASE)
    if not m_email:
        m_email = re.search(r"\b([\w.+-]{2,}@[\w-]+\.[a-z]{2,})\b", src)
    if m_email:
        info["email_raw"] = m_email.group(1).strip()

    # Website
    for pat in [
        r'<a[^>]+class="[^"]*website[^"]*"[^>]+href="(https?://[^"]+)"',
        r'href="(https?://(?!(?:www\.)?yellowpages\.in)[^"\s]+)"[^>]*>\s*(?:Website|Visit|www\.)',
    ]:
        m = re.search(pat, src, re.IGNORECASE)
        if m:
            info["website"] = m.group(1).strip()
            break

    # Additional phone numbers from tel: links
    tels = re.findall(r'href="tel:([+\d\s\-()/]{7,})"', src, re.IGNORECASE)
    if tels:
        info["tel_list"] = tels

    return info if info else None


# ─── Main scraper class ────────────────────────────────────────────────────────

class YellowPagesScraper(BaseScraper):

    def __init__(self, delay: float = 1.5, proxy: Optional[str] = None):
        super().__init__(delay=delay, proxy=proxy)

    # ── Search-results pages (sync, run in executor) ───────────────────────

    def _fetch_search_page(
        self, session: requests.Session, keyword: str, city: str, page: int
    ) -> list[dict]:
        """
        Fetch one search-results page and return a list of listing dicts.
        """
        url = _search_url(keyword, city, page)
        self._log.debug("YP search page %d: %s", page, url)
        try:
            resp = session.get(url, timeout=25)
            resp.raise_for_status()
        except Exception as exc:
            self._log.debug("search page %d failed: %s", page, exc)
            return []

        blocks   = _split_listings(resp.text)
        listings = []
        for block in blocks:
            info = _parse_listing_block(block)
            if info:
                listings.append(info)

        self._log.debug("YP page %d → %d listings", page, len(listings))
        return listings

    # ── Main entry-point ───────────────────────────────────────────────────

    async def scrape(
        self,
        keyword:     str,
        location:    str,
        max_results: int  = 30,
        headless:    bool = True,
    ) -> list[Lead]:

        city    = location.strip().split(",")[0].strip()
        loop    = asyncio.get_event_loop()
        session = _make_session()

        all_listings: list[dict] = []
        seen_urls:    set[str]   = set()

        # ── Paginated search-results fetches ──────────────────────────────
        for page_num in range(1, 21):
            page_listings = await loop.run_in_executor(
                None,
                functools.partial(self._fetch_search_page, session, keyword, city, page_num),
            )
            if not page_listings:
                break

            added = 0
            for item in page_listings:
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                all_listings.append(item)
                added += 1
                if len(all_listings) >= max_results:
                    break

            if added == 0:
                break
            if len(all_listings) >= max_results:
                break

            await asyncio.sleep(random.uniform(0.8, 1.6))

        # ── Parallel profile fetches for extra fields ──────────────────────
        sem = asyncio.Semaphore(6)

        async def enrich_item(item: dict) -> dict:
            async with sem:
                await asyncio.sleep(random.uniform(0.2, 0.8))
                extra = await loop.run_in_executor(
                    None,
                    functools.partial(_scrape_profile_static, session, item["url"]),
                )
                if extra:
                    if extra.get("website") and not item.get("website"):
                        item["website"] = extra["website"]
                    if extra.get("email_raw") and not item.get("email"):
                        item["email"] = extra["email_raw"]
                    # Merge any additional phone numbers
                    if extra.get("tel_list") and not item.get("phone"):
                        nums = self._extract_all_phones(extra["tel_list"][0])
                        if nums:
                            item["phone"] = nums[0]
            return item

        enriched_items = await asyncio.gather(
            *[enrich_item(item) for item in all_listings[:max_results]]
        )

        session.close()

        # ── Build Lead objects ─────────────────────────────────────────────
        leads:     list[Lead] = []
        seen_keys: set[str]   = set()

        for info in enriched_items:
            name = self._clean_text(info.get("name", ""))
            if not name:
                continue

            raw_phone = info.get("phone", "")
            nums = self._extract_all_phones(raw_phone) if raw_phone else []
            phone = ", ".join(filter(None, [self._clean_phone(n) for n in nums]))

            key = self._dedup_key(name, phone)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            email = info.get("email", "")
            if email and not self._valid_email(email):
                email = ""

            addr      = self._clean_text(info.get("address", ""))
            area      = self._clean_text(info.get("area", ""))
            city_part = self._clean_text(info.get("city_part") or city.title())

            lead = Lead()
            lead.add_source(SOURCE, info.get("url", ""))
            lead.name     = name
            lead.phone    = phone
            lead.email    = self._clean_text(email)
            lead.website  = info.get("website", "")
            lead.address  = addr or area
            lead.city     = city_part
            lead.state    = self._clean_text(info.get("state", ""))
            lead.zip_code = info.get("zip_code") or self._extract_pincode(addr or area)
            lead.category = self._clean_text(info.get("category") or keyword)
            lead.rating   = float(info.get("rating") or 0.0)
            lead.reviews  = int(info.get("reviews") or 0)
            lead.hours    = self._clean_text(info.get("hours", ""))
            leads.append(lead)

        return leads

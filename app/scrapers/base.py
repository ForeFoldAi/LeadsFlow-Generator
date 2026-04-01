from __future__ import annotations
"""Shared base class and utilities for all LeadsFlow scrapers.

Provides
────────
  - Randomised User-Agent rotation
  - page.goto() with exponential-backoff retry
  - Playwright resource blocking (images, fonts, analytics)
  - Human-like scroll to flush lazy-loaded cards
  - JSON-LD structured-data extraction (LocalBusiness schema)
  - Next.js __NEXT_DATA__ hydration-JSON extraction
  - Indian phone normalisation + multi-phone extraction
  - Pincode extraction from address strings
  - Composite dedup key  (normalised name + phone)
  - Email validation with blocklist
  - Browser context factory (randomised UA, viewport, IST timezone,
    sec-ch-ua headers, proxy support)
"""

import asyncio
import json
import logging
import random
import re
import unicodedata
from typing import Optional

# ── User-Agent pool ───────────────────────────────────────────────────────────
_USER_AGENTS: list[str] = [
    # Chrome/Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome/macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Chrome/Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    # Safari/macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

_EMAIL_RE = re.compile(r"^[\w.+-]{2,}@[\w-]{2,}\.[a-z]{2,6}$", re.IGNORECASE)
_EMAIL_BLOCKLIST = frozenset({
    "noreply", "no-reply", "donotreply", "mailer-daemon",
    "sulekha.com", "yellowpages.in", "example.com",
})

_ANALYTICS_DOMAINS = (
    "google-analytics", "googletagmanager", "facebook.net",
    "hotjar.com", "crisp.chat", "mxpnl.com",
    "doubleclick.net", "googlesyndication", "adservice.google",
    "clarity.ms", "segment.io", "mixpanel.com",
)


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


class BaseScraper:
    """Abstract base for all LeadsFlow scrapers.  Subclass and call super().__init__()."""

    def __init__(self, delay: float = 1.5, proxy: Optional[str] = None):
        self.delay = delay
        self.proxy = proxy
        self._log = logging.getLogger(self.__class__.__name__)

    # ── Timing ────────────────────────────────────────────────────────────────
    async def _pause(self) -> None:
        await asyncio.sleep(random.uniform(self.delay * 0.8, self.delay * 1.4))

    # ── Playwright: navigation ────────────────────────────────────────────────
    async def _goto(self, page, url: str, retries: int = 3) -> bool:
        """Navigate to url with exponential-backoff retry on failure."""
        for attempt in range(retries):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                return True
            except Exception as exc:
                self._log.debug(
                    "goto %s failed (attempt %d/%d): %s", url, attempt + 1, retries, exc
                )
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)   # 1s → 2s → 4s
        return False

    # ── Playwright: resource blocking ─────────────────────────────────────────
    async def _block_resources(self, route) -> None:
        """
        Abort requests for non-essential resource types and known analytics
        domains.  Speeds up page loads by ~40% and reduces bandwidth.
        """
        if route.request.resource_type in ("image", "font", "media", "stylesheet"):
            await route.abort()
            return
        if any(d in route.request.url for d in _ANALYTICS_DOMAINS):
            await route.abort()
            return
        await route.continue_()

    # ── Playwright: human-like scroll ─────────────────────────────────────────
    async def _human_scroll(self, page) -> None:
        """Scroll gradually to trigger lazy-loaded cards and appear less bot-like."""
        for y in range(300, 2_400, 500):
            await page.evaluate(f"window.scrollTo(0, {y})")
            await asyncio.sleep(random.uniform(0.1, 0.3))

    # ── Structured data: JSON-LD ──────────────────────────────────────────────
    async def _extract_jsonld(self, page) -> dict:
        """
        Parse every <script type="application/ld+json"> block on the page
        and return the first LocalBusiness / Organization node as a plain dict.
        Returns {} when nothing useful is found.
        """
        _LOCAL_BIZ_TYPES = (
            "LocalBusiness", "Organization", "Store",
            "Restaurant", "MedicalBusiness", "EducationalOrganization",
            "ProfessionalService", "HomeAndConstructionBusiness",
        )
        try:
            scripts = await page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    raw  = await script.inner_text()
                    data = json.loads(raw)
                    # Flatten @graph arrays
                    nodes = data.get("@graph", [data])
                    for node in nodes:
                        t = node.get("@type", "")
                        if isinstance(t, list):
                            t = " ".join(t)
                        if any(biz in t for biz in _LOCAL_BIZ_TYPES):
                            info = self._jsonld_to_info(node)
                            if info:
                                return info
                except Exception:
                    continue
        except Exception as exc:
            self._log.debug("JSON-LD extraction error: %s", exc)
        return {}

    @staticmethod
    def _jsonld_to_info(node: dict) -> dict:
        """Convert a JSON-LD LocalBusiness node to a flat info dict."""
        info: dict = {}
        if node.get("name"):
            info["name"] = str(node["name"]).strip()

        # Phone
        for key in ("telephone", "phone", "contactPoint"):
            val = node.get(key, "")
            if isinstance(val, dict):
                val = val.get("telephone", "")
            if val and isinstance(val, str):
                info["phone"] = val.strip()
                break

        # Address
        addr = node.get("address", {})
        if isinstance(addr, dict):
            parts = [
                addr.get("streetAddress", ""),
                addr.get("addressLocality", ""),
                addr.get("addressRegion", ""),
                addr.get("postalCode", ""),
            ]
            info["address"]  = ", ".join(p for p in parts if p)
            info["city"]     = addr.get("addressLocality", "")
            info["state"]    = addr.get("addressRegion", "")
            info["zip_code"] = addr.get("postalCode", "")
        elif isinstance(addr, str) and addr:
            info["address"] = addr

        # Ratings
        agg = node.get("aggregateRating", {})
        if isinstance(agg, dict):
            try:
                rv = float(agg.get("ratingValue", 0))
                rc = int(agg.get("reviewCount", 0))
                if 0 < rv <= 5:
                    info["rating"]  = rv
                    info["reviews"] = rc
            except (ValueError, TypeError):
                pass

        # Website / email
        url   = node.get("url", "")
        email = node.get("email", "")
        if url   and isinstance(url, str):
            info["website"] = url
        if email and isinstance(email, str) and "@" in email:
            info["email"] = email

        return info

    # ── Structured data: Next.js __NEXT_DATA__ ────────────────────────────────
    async def _extract_next_data(self, page) -> dict:
        """
        Extract Next.js server-side hydration JSON from __NEXT_DATA__.
        Many modern Indian business-directory sites use Next.js and embed
        the complete business record here — no CSS selector work needed.
        Returns the deepest relevant dict found, or {} on failure.
        """
        try:
            raw = await page.eval_on_selector(
                "#__NEXT_DATA__", "el => el.textContent"
            )
            data  = json.loads(raw)
            props = data.get("props", {}).get("pageProps", {})
            for key in (
                "businessData", "companyDetails", "vendorDetails",
                "profileData", "listingData", "businessInfo", "detail",
            ):
                if key in props and isinstance(props[key], dict):
                    return props[key]
            return props
        except Exception:
            return {}

    # ── Data cleaning ─────────────────────────────────────────────────────────
    @staticmethod
    def _clean_phone(phone: str) -> str:
        """Normalise a single Indian phone number to pure digits (7–15 chars)."""
        if not phone:
            return ""
        digits = re.sub(r"[^\d+]", "", phone)
        if re.match(r"^\+?91(\d{10})$", digits):
            digits = re.sub(r"^\+?91", "", digits)
        elif re.match(r"^0(\d{10})$", digits):
            digits = digits[1:]
        return digits if 7 <= len(digits) <= 15 else ""

    @staticmethod
    def _extract_all_phones(text: str) -> list[str]:
        """
        Extract every valid Indian phone number from a text blob.
        Returns a deduplicated list in order of appearance.
        """
        raw = re.findall(
            r"(?:\+91[-\s]?|0)?[6-9]\d{9}"   # 10-digit mobile (starts 6-9)
            r"|\b0\d{2,4}[-\s]\d{6,8}\b",     # STD-code landlines
            text,
        )
        seen: set[str] = set()
        result: list[str] = []
        for ph in raw:
            cleaned = BaseScraper._clean_phone(ph)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip() if value else ""

    @staticmethod
    def _extract_pincode(address: str) -> str:
        """Extract a 6-digit Indian PIN code from an address string."""
        m = re.search(r"\b([1-9]\d{5})\b", address)
        return m.group(1) if m else ""

    @staticmethod
    def _valid_email(email: str) -> bool:
        """Return True only for plausibly real, non-system email addresses."""
        email = (email or "").strip().lower()
        if not _EMAIL_RE.match(email):
            return False
        domain = email.split("@", 1)[-1]
        return not any(blocked in email or blocked == domain for blocked in _EMAIL_BLOCKLIST)

    @staticmethod
    def _dedup_key(name: str, phone: str) -> str:
        """
        Canonical key for cross-source deduplication.
        Strips legal-entity suffixes and uses the last 10 digits of the phone
        so 'ABC Pvt Ltd' and 'ABC Private Limited' hash to the same key.
        """
        n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        n = re.sub(r"\b(pvt|private|limited|ltd|llp|inc|co)\b\.?", "", n, flags=re.I)
        n = re.sub(r"[^a-z0-9]", "", n.lower())
        p = re.sub(r"\D", "", phone)[-10:] if phone else ""
        return f"{n}:{p}" if p else n

    # ── Browser context factory ───────────────────────────────────────────────
    def _ctx_kwargs(self) -> dict:
        """
        Build Playwright browser.new_context() kwargs with a randomised
        fingerprint: UA, viewport, locale, timezone, and realistic
        Chromium client-hint / sec-fetch headers.
        """
        return dict(
            viewport={
                "width":  random.choice([1280, 1366, 1440, 1920]),
                "height": random.choice([768, 800, 900, 1080]),
            },
            user_agent=_random_ua(),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language":            "en-IN,en;q=0.9,hi;q=0.8",
                "sec-ch-ua":                  '"Chromium";v="122", "Not(A:Brand";v="24"',
                "sec-ch-ua-mobile":           "?0",
                "sec-ch-ua-platform":         '"Windows"',
                "sec-fetch-dest":             "document",
                "sec-fetch-mode":             "navigate",
                "sec-fetch-site":             "none",
                "upgrade-insecure-requests":  "1",
            },
        )

    def _launch_kwargs(self, headless: bool = True) -> dict:
        """Build Playwright browser.launch() kwargs, including proxy if set."""
        kwargs: dict = {
            "headless": headless,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
            ],
        }
        if self.proxy:
            kwargs["proxy"] = {"server": self.proxy}
        return kwargs

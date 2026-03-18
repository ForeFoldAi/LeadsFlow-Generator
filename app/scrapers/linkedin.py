from __future__ import annotations
"""
LinkedIn Company scraper — strict location filtering.

Set env vars to skip interactive login:
  LINKEDIN_EMAIL=you@email.com
  LINKEDIN_PASSWORD=yourpassword
"""
import asyncio, os, re
from app.models.lead_dataclass import Lead

SOURCE = "LinkedIn"

# LinkedIn geo URNs for Indian + major cities
LINKEDIN_GEO_URNS = {
    "hyderabad":  "105556991",
    "mumbai":     "103596854",
    "bangalore":  "104869687",
    "bengaluru":  "104869687",
    "delhi":      "102713980",
    "new delhi":  "102713980",
    "chennai":    "102140898",
    "kolkata":    "104307705",
    "pune":       "106164952",
    "ahmedabad":  "102715500",
    "jaipur":     "106937448",
    "kochi":      "102775765",
    "new york":   "105080838",
    "london":     "90009496",
    "singapore":  "102454443",
    "dubai":      "106204383",
}


def _parse_location(location: str):
    city    = location.split(",")[0].strip()
    country = location.split(",")[-1].strip() if "," in location else "India"
    geo_urn = LINKEDIN_GEO_URNS.get(city.lower())
    return city, country, geo_urn


class LinkedInScraper:
    def __init__(self, delay: float = 2.5):
        self.delay = delay
        self._logged_in = False

    async def _pause(self, lo=None, hi=None):
        import random
        await asyncio.sleep(random.uniform(lo or self.delay * 0.9, hi or self.delay * 1.5))

    async def _login(self, page, email, password):
        await page.goto("https://www.linkedin.com/login",
                        wait_until="domcontentloaded", timeout=30000)
        await page.fill('input[name="session_key"]',      email)
        await page.fill('input[name="session_password"]', password)
        await page.click('button[type="submit"]')
        await self._pause(3, 5)
        self._logged_in = (
            "linkedin.com" in page.url and "login" not in page.url
        )

    async def scrape(self, keyword: str, location: str,
                     max_results: int = 20, headless: bool = True) -> list[Lead]:
        from playwright.async_api import async_playwright
        leads: list[Lead] = []

        email    = os.getenv("LINKEDIN_EMAIL",    "")
        password = os.getenv("LINKEDIN_PASSWORD", "")
        if not email or not password:
            print("  ⏭️   LinkedIn skipped — set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env")
            return leads

        target_city, country, geo_urn = _parse_location(location)
        print(f"    Searching: {keyword} | City: {target_city} | geo_urn: {geo_urn or 'text-only'}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = await ctx.new_page()
            await self._login(page, email, password)

            if not self._logged_in:
                print("  ⚠️  LinkedIn login failed. Check credentials.")
                await browser.close()
                return leads

            # ── Build search URL ──────────────────────────────────────────────
            kw = f"{keyword} {target_city}".replace(" ", "%20")

            if geo_urn:
                search_url = (
                    f"https://www.linkedin.com/search/results/companies/"
                    f"?keywords={kw}"
                    f"&geoUrn=%5B%22{geo_urn}%22%5D"
                    f"&origin=FACETED_SEARCH"
                )
            else:
                search_url = (
                    f"https://www.linkedin.com/search/results/companies/"
                    f"?keywords={kw}"
                    f"&origin=SWITCH_SEARCH_VERTICAL"
                )

            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await self._pause(2, 3)

            # Dismiss popups
            for sel in ['button[aria-label="Dismiss"]', 'button:has-text("Not now")',
                        'button:has-text("Skip")', 'button:has-text("Got it")']:
                try:
                    btn = page.locator(sel)
                    if await btn.first.is_visible(timeout=1500):
                        await btn.first.click(); await self._pause(0.5, 1)
                except Exception:
                    pass

            # ── Collect company page URLs ─────────────────────────────────────
            company_urls: list[str] = []
            seen: set[str] = set()
            no_new = 0

            for _ in range(6):  # scroll up to 6 pages
                anchors = await page.query_selector_all('a[href*="/company/"]')
                before = len(company_urls)
                for a in anchors:
                    href = await a.get_attribute("href") or ""
                    m = re.match(r"(https://www\.linkedin\.com/company/[^/?]+)", href)
                    if m and m.group(1) not in seen:
                        seen.add(m.group(1))
                        company_urls.append(m.group(1))
                        if len(company_urls) >= max_results * 3:
                            break
                no_new = 0 if len(company_urls) > before else no_new + 1
                if no_new >= 3 or len(company_urls) >= max_results * 3:
                    break
                await page.evaluate("window.scrollBy(0, 1200)")
                await self._pause()

            print(f"    Collected {len(company_urls)} URLs — visiting each for location check…")

            # ── Visit each page, extract, then STRICTLY filter by city ────────
            for url in company_urls:
                if len(leads) >= max_results:
                    break
                lead = await self._extract(page, url)
                if not lead:
                    continue

                # ── STRICT location filter ────────────────────────────────────
                hq_text = f"{lead.city} {lead.state} {lead.address}".lower()
                if target_city.lower() not in hq_text:
                    continue

                leads.append(lead)
                print(f"      ✓ {lead.name} | {lead.city}")
                await self._pause(0.8, 1.2)

            await browser.close()

        print(f"    ✅  {len(leads)} leads confirmed in {target_city}")
        return leads

    async def _extract(self, page, url: str) -> Lead | None:
        try:
            await page.goto(url + "/about/", wait_until="domcontentloaded", timeout=20000)
            await self._pause(1.5, 2.5)
            lead = Lead()
            lead.add_source(SOURCE, url)

            # Name
            for sel in ['h1.org-top-card-summary__title', 'h1[class*="org-top-card"]', 'h1']:
                el = await page.query_selector(sel)
                if el:
                    txt = (await el.inner_text()).strip()
                    if txt: lead.name = txt; break

            # Industry
            el = await page.query_selector('dt:has-text("Industry") + dd')
            if el: lead.category = (await el.inner_text()).strip()

            # Website
            el = await page.query_selector('dt:has-text("Website") + dd a')
            if el: lead.website = (await el.get_attribute("href") or "").strip()

            # Phone
            el = await page.query_selector('dt:has-text("Phone") + dd')
            if el: lead.phone = (await el.inner_text()).strip()

            # Headquarters → city / state (critical for location filter)
            el = await page.query_selector('dt:has-text("Headquarters") + dd')
            if el:
                hq = (await el.inner_text()).strip()
                lead.address = hq
                parts = [p.strip() for p in hq.split(",")]
                lead.city  = parts[0] if parts else ""
                lead.state = parts[1] if len(parts) > 1 else ""

            # Followers
            for sel in ['span[data-test-id="followers-count"]',
                        'p:has-text("followers")', 'span:has-text("followers")']:
                el = await page.query_selector(sel)
                if el:
                    txt = (await el.inner_text()).strip()
                    nums = re.findall(r"[\d,]+", txt)
                    if nums:
                        try: lead.reviews = int(nums[0].replace(",", "")); break
                        except: pass

            lead.rating = 4.0 if lead.name else 0.0
            return lead if lead.name else None
        except Exception:
            return None

from __future__ import annotations
"""
Instagram Business Profile scraper.

Searches Instagram for business accounts matching keyword + location.
Extracts: name, bio (category), website, phone (from bio), location.

Credentials required for full access:
  Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD env vars, or enter interactively.
"""
import asyncio, os, re
from app.models.lead_dataclass import Lead

SOURCE = "Instagram"
BASE   = "https://www.instagram.com"


class InstagramScraper:
    def __init__(self, delay: float = 3.0):
        self.delay = delay
        self._logged_in = False

    async def _pause(self, lo=None, hi=None):
        import random
        await asyncio.sleep(random.uniform(lo or self.delay * 0.8, hi or self.delay * 1.4))

    async def _login(self, page):
        username = os.getenv("INSTAGRAM_USERNAME", "")
        password = os.getenv("INSTAGRAM_PASSWORD", "")
        if not username:
            print("  ⚠️   Skipping Instagram (no credentials)")
            return False
        try:
            await page.goto(f"{BASE}/accounts/login/", wait_until="domcontentloaded", timeout=20000)
            await self._pause(1.5, 2)
            await page.fill('input[name="username"]', username)
            await page.fill('input[name="password"]', password)
            await page.click('button[type="submit"]')
            await self._pause(3, 4)
            # Dismiss "Save login info" / "Turn on notifications" popups
            for txt in ["Not Now", "Not now", "Skip"]:
                try:
                    btn = page.locator(f'button:has-text("{txt}")')
                    if await btn.first.is_visible(timeout=2000):
                        await btn.first.click()
                        await self._pause(0.5, 1)
                except Exception:
                    pass
            self._logged_in = "instagram.com" in page.url and "login" not in page.url
            if self._logged_in:
                print("  ✅  Instagram login successful")
            return self._logged_in
        except Exception as e:
            print(f"  ⚠️   Instagram login failed ({e})")
            return False

    async def scrape(self, keyword: str, location: str,
                     max_results: int = 20, headless: bool = True) -> list[Lead]:
        from playwright.async_api import async_playwright
        leads: list[Lead] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                           "Mobile/15E148 Safari/604.1",
                locale="en-US",
            )
            page = await ctx.new_page()

            logged_in = await self._login(page)
            if not logged_in:
                await browser.close()
                return leads

            # Search Instagram for accounts
            query = f"{keyword} {location}".replace(" ", "%20")
            await page.goto(f"{BASE}/explore/search/keyword/?q={query}",
                            wait_until="domcontentloaded", timeout=30000)
            await self._pause(2, 3)

            # Collect profile links
            profile_urls: list[str] = []
            seen: set[str] = set()
            no_new = 0

            while len(profile_urls) < max_results and no_new < 3:
                anchors = await page.query_selector_all('a[href^="/"][href$="/"]')
                before = len(profile_urls)
                for a in anchors:
                    href = await a.get_attribute("href") or ""
                    m = re.match(r"^/([^/]{2,30})/$", href)
                    if m:
                        username = m.group(1)
                        skip = {"explore", "accounts", "direct", "stories", "reels",
                                "tv", "p", "location", "tags", "login", "help"}
                        if username not in skip:
                            full = BASE + href
                            if full not in seen:
                                seen.add(full)
                                profile_urls.append(full)
                                if len(profile_urls) >= max_results:
                                    break
                no_new = 0 if len(profile_urls) > before else no_new + 1
                await page.evaluate("window.scrollBy(0, 800)")
                await self._pause()

            print(f"    Found {len(profile_urls)} Instagram profiles")

            # Visit each profile
            for url in profile_urls[:max_results]:
                lead = await self._extract(page, url)
                if lead:
                    leads.append(lead)
                await self._pause()

            await browser.close()
        return leads

    async def _extract(self, page, url: str) -> Lead | None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._pause(1.5, 2.5)

            lead = Lead()
            lead.add_source(SOURCE, url)

            # Name (display name)
            el = await page.query_selector('h1, h2[class*="_aacl"]')
            if el: lead.name = (await el.inner_text()).strip()

            # Category / bio
            els = await page.query_selector_all('div[class*="_aa_c"] span, div[class*="biography"]')
            bio_parts = []
            for el in els[:3]:
                txt = (await el.inner_text()).strip()
                if txt: bio_parts.append(txt)
            bio = " ".join(bio_parts)
            lead.category = bio[:80] if bio else ""

            # Phone from bio
            phone_match = re.search(r"[\+\d][\d\s\-\(\)]{8,15}", bio)
            if phone_match:
                lead.phone = re.sub(r"[^\d\+]", "", phone_match.group()).strip()

            # Website
            el = await page.query_selector('a[class*="_aacl"][href^="http"]:not([href*="instagram"])')
            if el:
                lead.website = await el.get_attribute("href") or ""

            # Location from bio
            loc_match = re.search(r"📍\s*(.+?)(?:\n|$)", bio)
            if loc_match:
                lead.city = loc_match.group(1).strip()[:50]

            # Follower count as proxy for reviews
            el = await page.query_selector('span[class*="followers"], a[href*="followers"] span')
            if el:
                txt = (await el.inner_text()).strip().replace(",", "")
                try:
                    if "K" in txt: lead.reviews = int(float(txt.replace("K","")) * 1000)
                    elif "M" in txt: lead.reviews = int(float(txt.replace("M","")) * 1000000)
                    else: lead.reviews = int(txt)
                except: pass

            # Instagram business profiles don't have star ratings — default 4.0
            lead.rating = 4.0 if lead.name else 0.0

            return lead if lead.name and len(lead.name) > 1 else None
        except Exception:
            return None

from __future__ import annotations
"""
Twitter / X Business Profile scraper.

Searches Twitter/X for business accounts matching keyword + location.
Extracts: name, bio (category/description), website, location, follower count.

Credentials required:
  Set TWITTER_USERNAME and TWITTER_PASSWORD env vars, or enter interactively.
"""
import asyncio, os, re
from app.models.lead_dataclass import Lead

SOURCE = "Twitter"
BASE   = "https://x.com"


class TwitterScraper:
    def __init__(self, delay: float = 3.0):
        self.delay = delay
        self._logged_in = False

    async def _pause(self, lo=None, hi=None):
        import random
        await asyncio.sleep(random.uniform(lo or self.delay * 0.8, hi or self.delay * 1.4))

    async def _login(self, page):
        username = os.getenv("TWITTER_USERNAME", "")
        password = os.getenv("TWITTER_PASSWORD", "")
        if not username:
            print("  ⚠️   Skipping Twitter (no credentials)")
            return False
        try:
            await page.goto(f"{BASE}/i/flow/login", wait_until="domcontentloaded", timeout=20000)
            await self._pause(2, 3)
            # Step 1: username
            await page.fill('input[autocomplete="username"]', username)
            await page.keyboard.press("Enter")
            await self._pause(1.5, 2)
            # Step 2: password
            await page.fill('input[name="password"]', password)
            await page.keyboard.press("Enter")
            await self._pause(3, 4)
            self._logged_in = "x.com" in page.url and "login" not in page.url
            if self._logged_in:
                print("  ✅  Twitter login successful")
            return self._logged_in
        except Exception as e:
            print(f"  ⚠️   Twitter login failed ({e})")
            return False

    async def scrape(self, keyword: str, location: str,
                     max_results: int = 20, headless: bool = True) -> list[Lead]:
        from playwright.async_api import async_playwright
        leads: list[Lead] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"])
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = await ctx.new_page()

            logged_in = await self._login(page)
            if not logged_in:
                await browser.close()
                return leads

            # Search Twitter for accounts
            query = f"{keyword} {location}".replace(" ", "%20")
            search_url = f"{BASE}/search?q={query}&src=typed_query&f=user"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await self._pause(2, 3)

            # Collect profile links by scrolling
            profile_urls: list[str] = []
            seen: set[str] = set()
            no_new = 0

            while len(profile_urls) < max_results and no_new < 4:
                anchors = await page.query_selector_all('a[href^="/"][role="link"]')
                before = len(profile_urls)
                for a in anchors:
                    href = await a.get_attribute("href") or ""
                    m = re.match(r"^/([A-Za-z0-9_]{1,15})$", href)
                    if m:
                        handle = m.group(1)
                        skip = {"home", "explore", "notifications", "messages",
                                "search", "login", "i", "compose", "settings"}
                        if handle.lower() not in skip:
                            full = BASE + href
                            if full not in seen:
                                seen.add(full)
                                profile_urls.append(full)
                                if len(profile_urls) >= max_results:
                                    break
                no_new = 0 if len(profile_urls) > before else no_new + 1
                await page.evaluate("window.scrollBy(0, 1000)")
                await self._pause()

            print(f"    Found {len(profile_urls)} Twitter profiles")

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

            # Display name
            el = await page.query_selector('div[data-testid="UserName"] span')
            if el: lead.name = (await el.inner_text()).strip()

            # Bio as category
            el = await page.query_selector('div[data-testid="UserDescription"]')
            if el:
                bio = (await el.inner_text()).strip()
                lead.category = bio[:100]
                # Extract phone from bio
                m = re.search(r"[\+\d][\d\s\-\(\)]{8,15}", bio)
                if m:
                    lead.phone = re.sub(r"[^\d\+]", "", m.group()).strip()

            # Location
            el = await page.query_selector('span[data-testid="UserLocation"]')
            if el:
                loc = (await el.inner_text()).strip()
                lead.city = loc.split(",")[0].strip()[:50]

            # Website
            el = await page.query_selector('a[data-testid="UserUrl"]')
            if el:
                lead.website = await el.get_attribute("href") or (await el.inner_text()).strip()

            # Followers as proxy for review count
            el = await page.query_selector('a[href$="/followers"] span span')
            if el:
                txt = (await el.inner_text()).strip().replace(",", "")
                try:
                    if "K" in txt: lead.reviews = int(float(txt.replace("K","")) * 1000)
                    elif "M" in txt: lead.reviews = int(float(txt.replace("M","")) * 1000000)
                    else: lead.reviews = int(txt)
                except: pass

            lead.rating = 4.0 if lead.name else 0.0
            return lead if lead.name and len(lead.name) > 1 else None
        except Exception:
            return None

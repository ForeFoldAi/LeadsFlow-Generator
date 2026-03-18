from __future__ import annotations
"""
Facebook Business Pages scraper.

Searches Facebook for business pages matching keyword + location.
Extracts: name, category, phone, website, address, rating, about info.

Credentials (optional — improves results):
  Set FACEBOOK_EMAIL and FACEBOOK_PASSWORD env vars, or enter interactively.
  Without login, only public page info is accessible.
"""
import asyncio, os, re
from app.models.lead_dataclass import Lead

SOURCE = "Facebook"
BASE   = "https://www.facebook.com"


class FacebookScraper:
    def __init__(self, delay: float = 2.5):
        self.delay = delay
        self._logged_in = False

    async def _pause(self, lo=None, hi=None):
        import random
        await asyncio.sleep(random.uniform(lo or self.delay * 0.8, hi or self.delay * 1.4))

    async def _try_login(self, page):
        email    = os.getenv("FACEBOOK_EMAIL", "")
        password = os.getenv("FACEBOOK_PASSWORD", "")
        if not email:
            return
        try:
            await page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=20000)
            await page.fill('input[name="email"]',  email)
            await page.fill('input[name="pass"]',   password)
            await page.click('button[name="login"]')
            await self._pause(2, 3)
            self._logged_in = "facebook.com" in page.url and "login" not in page.url
            if self._logged_in:
                print("  ✅  Facebook login successful")
        except Exception as e:
            print(f"  ⚠️   Facebook login failed ({e}) — continuing without login")

    async def scrape(self, keyword: str, location: str,
                     max_results: int = 30, headless: bool = True) -> list[Lead]:
        from playwright.async_api import async_playwright
        leads: list[Lead] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = await ctx.new_page()

            await self._try_login(page)

            # Search Facebook for business pages
            query = f"{keyword} {location}".replace(" ", "%20")
            search_url = f"{BASE}/search/pages/?q={query}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await self._pause(2, 3)

            # Dismiss any popups
            for sel in ['[aria-label="Close"]', '[data-testid="cookie-policy-dialog-accept-button"]']:
                try:
                    btn = page.locator(sel)
                    if await btn.first.is_visible(timeout=2000):
                        await btn.first.click()
                        await self._pause(0.5, 1)
                except Exception:
                    pass

            # Collect page URLs by scrolling
            page_urls: list[str] = []
            seen: set[str] = set()
            no_new = 0

            while len(page_urls) < max_results and no_new < 4:
                anchors = await page.query_selector_all('a[href*="facebook.com/"]')
                before = len(page_urls)
                for a in anchors:
                    href = await a.get_attribute("href") or ""
                    m = re.match(r"(https://www\.facebook\.com/(?!search|login|help|policies)[^/?#\s]+)", href)
                    if m:
                        clean = m.group(1).rstrip("/")
                        if clean not in seen and "/profile.php" not in clean:
                            seen.add(clean)
                            page_urls.append(clean)
                            if len(page_urls) >= max_results:
                                break

                no_new = 0 if len(page_urls) > before else no_new + 1
                await page.evaluate("window.scrollBy(0, 1000)")
                await self._pause()

            print(f"    Found {len(page_urls)} Facebook page URLs")

            # Visit each page and extract info
            for url in page_urls[:max_results]:
                lead = await self._extract(page, url)
                if lead:
                    leads.append(lead)
                await self._pause()

            await browser.close()
        return leads

    async def _extract(self, page, url: str) -> Lead | None:
        try:
            await page.goto(url + "/about", wait_until="domcontentloaded", timeout=20000)
            await self._pause(1.5, 2.5)

            lead = Lead()
            lead.add_source(SOURCE, url)

            # Page name
            for sel in ['h1[class*="x1heor9g"]', 'h1', 'title']:
                el = await page.query_selector(sel)
                if el:
                    txt = (await el.inner_text()).strip()
                    if txt and txt != "Facebook":
                        lead.name = txt.split("|")[0].strip()
                        break

            # Category
            el = await page.query_selector('a[href*="/pages/category/"], span[class*="x193iq5w"]')
            if el:
                lead.category = (await el.inner_text()).strip()

            # Phone
            anchors = await page.query_selector_all('a[href^="tel:"]')
            for a in anchors:
                href = await a.get_attribute("href") or ""
                phone = href.replace("tel:", "").strip()
                if phone:
                    lead.phone = phone
                    break

            # Website
            anchors = await page.query_selector_all('a[href*="l.facebook.com/l.php"]')
            for a in anchors:
                href = await a.get_attribute("href") or ""
                m = re.search(r"u=([^&]+)", href)
                if m:
                    import urllib.parse
                    decoded = urllib.parse.unquote(m.group(1))
                    if "facebook.com" not in decoded:
                        lead.website = decoded
                        break

            # Address — look for location text
            els = await page.query_selector_all('div[class*="x1i10hfl"] span, span[dir="auto"]')
            for el in els:
                txt = (await el.inner_text()).strip()
                if re.search(r"\d{3,}", txt) and len(txt) > 10 and len(txt) < 150:
                    if any(w in txt.lower() for w in ["street", "road", "ave", "blvd",
                                                       "nagar", "colony", "district"]):
                        lead.address = txt
                        parts = txt.split(",")
                        lead.city = parts[-2].strip() if len(parts) >= 2 else ""
                        break

            # Rating
            el = await page.query_selector('span[class*="rating"], div[aria-label*="out of 5"]')
            if el:
                label = await el.get_attribute("aria-label") or await el.inner_text()
                m = re.search(r"([\d.]+)", label)
                if m:
                    try: lead.rating = float(m.group(1))
                    except: pass

            # Reviews
            el = await page.query_selector('span[class*="reviews"], a[href*="reviews"]')
            if el:
                txt = (await el.inner_text()).strip()
                nums = re.findall(r"[\d,]+", txt)
                if nums:
                    try: lead.reviews = int(nums[0].replace(",", ""))
                    except: pass

            return lead if lead.name and len(lead.name) > 1 else None
        except Exception:
            return None

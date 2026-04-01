from __future__ import annotations
"""Better Business Bureau scraper (bbb.org)."""
import asyncio, re
from app.models.lead_dataclass import Lead

SOURCE = "BBB"
BASE   = "https://www.bbb.org"


class BBBScraper:
    def __init__(self, delay: float = 2.0):
        self.delay = delay

    async def _pause(self):
        import random
        await asyncio.sleep(random.uniform(self.delay * 0.9, self.delay * 1.4))

    async def scrape(self, keyword: str, location: str, max_results: int = 30, headless: bool = True) -> list[Lead]:
        from playwright.async_api import async_playwright
        leads: list[Lead] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"])
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = await ctx.new_page()
            page_num = 1
            collected_urls: list[str] = []

            while len(collected_urls) < max_results:
                url = (
                    f"{BASE}/search?find_text={keyword.replace(' ', '+')}"
                    f"&find_loc={location.replace(' ', '+')}&page={page_num}"
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await self._pause()

                cards = await page.query_selector_all('div[class*="SearchResult"], li[class*="result"]')
                if not cards:
                    # Try alternative selectors
                    cards = await page.query_selector_all('div.result-container')
                if not cards:
                    break

                for card in cards:
                    a = await card.query_selector('a[href*="/profile/"]')
                    if a:
                        href = await a.get_attribute("href") or ""
                        full = BASE + href if href.startswith("/") else href
                        if full not in collected_urls:
                            collected_urls.append(full)
                            if len(collected_urls) >= max_results:
                                break

                page_num += 1
                if page_num > 5:
                    break

            # Visit each profile page
            for biz_url in collected_urls[:max_results]:
                lead = await self._extract(page, biz_url)
                if lead:
                    leads.append(lead)
                await self._pause()

            await browser.close()
        return leads

    async def _extract(self, page, url: str) -> Lead | None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._pause()
            lead = Lead()
            lead.add_source(SOURCE, url)

            # Name
            el = await page.query_selector('h1[itemprop="name"], h1.bds-body')
            if not el:
                el = await page.query_selector('h1')
            if el: lead.name = (await el.inner_text()).strip()

            # Category
            el = await page.query_selector('p[class*="category"], span[class*="category"]')
            if el: lead.category = (await el.inner_text()).strip()

            # BBB Rating (letter: A+, A, B, etc.) — convert to 0–5 scale
            el = await page.query_selector('div[class*="LetterGrade"] span, span[class*="rating-letter"]')
            if el:
                grade = (await el.inner_text()).strip()
                grade_map = {"A+": 5.0, "A": 4.7, "A-": 4.5, "B+": 4.2, "B": 4.0,
                             "B-": 3.7, "C+": 3.5, "C": 3.2, "C-": 3.0,
                             "D+": 2.5, "D": 2.0, "D-": 1.5, "F": 1.0}
                lead.rating = grade_map.get(grade, 0.0)
                lead.hours  = f"BBB Grade: {grade}"   # store grade in hours field

            # Customer review rating
            el = await page.query_selector('p[class*="starRating"] span, span[class*="CustomerReviews"]')
            if el:
                txt = (await el.inner_text()).strip()
                m = re.search(r"([\d.]+)", txt)
                if m:
                    try:
                        star = float(m.group(1))
                        if star > lead.rating:   # use higher of the two
                            lead.rating = star
                    except: pass

            # Review count
            el = await page.query_selector('a[href*="reviews"] span, p[class*="reviewCount"]')
            if el:
                txt = (await el.inner_text()).strip()
                nums = re.findall(r"[\d,]+", txt)
                if nums:
                    try: lead.reviews = int(nums[0].replace(",", ""))
                    except: pass

            # Phone
            el = await page.query_selector('a[href^="tel:"], span[itemprop="telephone"]')
            if el:
                href = await el.get_attribute("href")
                lead.phone = href.replace("tel:", "") if href else (await el.inner_text()).strip()

            # Address
            for sel, attr in [
                ('span[itemprop="streetAddress"]', "streetAddress"),
                ('span[itemprop="addressLocality"]', "city"),
                ('span[itemprop="addressRegion"]', "state"),
                ('span[itemprop="postalCode"]', "zip_code"),
            ]:
                el = await page.query_selector(sel)
                if el:
                    val = (await el.inner_text()).strip()
                    if attr == "streetAddress": lead.address  = val
                    elif attr == "city":        lead.city     = val
                    elif attr == "state":       lead.state    = val
                    elif attr == "zip_code":    lead.zip_code = val

            # Website
            el = await page.query_selector('a[class*="websiteLink"], a[data-type="business-website"]')
            if el:
                lead.website = await el.get_attribute("href") or (await el.inner_text()).strip()

            return lead if lead.name else None
        except Exception:
            return None

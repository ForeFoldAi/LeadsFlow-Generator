from __future__ import annotations
"""Yelp scraper."""
import asyncio, re
from app.models.lead_dataclass import Lead

SOURCE = "Yelp"
BASE   = "https://www.yelp.com"


class YelpScraper:
    def __init__(self, delay: float = 1.8):
        self.delay = delay

    async def _pause(self):
        import random
        await asyncio.sleep(random.uniform(self.delay * 0.8, self.delay * 1.4))

    async def scrape(self, keyword: str, location: str, max_results: int = 30, headless: bool = True) -> list[Lead]:
        from playwright.async_api import async_playwright
        leads: list[Lead] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"])
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = await ctx.new_page()

            collected_urls: list[str] = []
            offset = 0

            while len(collected_urls) < max_results:
                url = f"{BASE}/search?find_desc={keyword.replace(' ', '+')}&find_loc={location.replace(' ', '+')}&start={offset}"
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await self._pause()

                # Collect business links from search results
                anchors = await page.query_selector_all('a[href*="/biz/"]')
                found_this_page = 0
                for a in anchors:
                    href = await a.get_attribute("href") or ""
                    # Filter to actual biz pages (not ads/nav)
                    if re.match(r"^/biz/[a-z0-9\-]+$", href):
                        full = BASE + href
                        if full not in collected_urls:
                            collected_urls.append(full)
                            found_this_page += 1
                            if len(collected_urls) >= max_results:
                                break

                if found_this_page == 0:
                    break  # No more results
                offset += 10

            # Scrape each business page
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
            el = await page.query_selector('h1[class*="businessName"], h1.css-foyide')
            if not el:
                el = await page.query_selector('h1')
            if el: lead.name = (await el.inner_text()).strip()

            # Category
            cats = await page.query_selector_all('span[class*="css-chandq"] a, a[href*="/c/"]')
            if cats:
                texts = [(await c.inner_text()).strip() for c in cats[:2]]
                lead.category = ", ".join(t for t in texts if t)

            # Rating
            el = await page.query_selector('div[aria-label*="star rating"]')
            if el:
                label = await el.get_attribute("aria-label") or ""
                m = re.search(r"([\d.]+)\s+star", label)
                if m:
                    try: lead.rating = float(m.group(1))
                    except: pass

            # Reviews
            el = await page.query_selector('a[href*="#reviews"] span, span[class*="reviewCount"]')
            if el:
                txt = (await el.inner_text()).strip()
                nums = re.findall(r"[\d,]+", txt)
                if nums:
                    try: lead.reviews = int(nums[0].replace(",", ""))
                    except: pass

            # Phone
            el = await page.query_selector('p[class*="css-1p9ibgf"] + p, a[href^="tel:"]')
            if el:
                if await el.get_attribute("href"):
                    lead.phone = (await el.get_attribute("href") or "").replace("tel:", "")
                else:
                    lead.phone = (await el.inner_text()).strip()

            # Address
            addr_parts = []
            for sel in ['address span[itemprop="streetAddress"]',
                        'address span[itemprop="addressLocality"]',
                        'address span[itemprop="addressRegion"]',
                        'address span[itemprop="postalCode"]']:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    addr_parts.append(text)

            if len(addr_parts) >= 2:
                lead.address  = ", ".join(addr_parts)
                lead.city     = addr_parts[1] if len(addr_parts) > 1 else ""
                lead.state    = addr_parts[2] if len(addr_parts) > 2 else ""
                lead.zip_code = addr_parts[3] if len(addr_parts) > 3 else ""
            elif not addr_parts:
                el = await page.query_selector('address')
                if el: lead.address = (await el.inner_text()).strip().replace("\n", ", ")

            # Website
            el = await page.query_selector('a[href*="biz_redir"]')
            if el: lead.website = await el.get_attribute("href") or ""

            # Hours (open/closed indicator)
            el = await page.query_selector('span[class*="open-closed"]')
            if el: lead.hours = (await el.inner_text()).strip()

            return lead if lead.name else None
        except Exception:
            return None

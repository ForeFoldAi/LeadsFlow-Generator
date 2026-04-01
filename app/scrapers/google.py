from __future__ import annotations
"""Google Maps scraper."""
import asyncio, re
from app.models.lead_dataclass import Lead

SOURCE = "Google Maps"


class GoogleMapsScraper:
    def __init__(self, delay: float = 1.5):
        self.delay = delay

    async def _pause(self):
        import random
        await asyncio.sleep(random.uniform(self.delay * 0.8, self.delay * 1.3))

    async def scrape(self, keyword: str, location: str, max_results: int = 30, headless: bool = True) -> list[Lead]:
        from playwright.async_api import async_playwright
        leads: list[Lead] = []
        query = f"{keyword} in {location}"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"])
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = await ctx.new_page()
            await page.goto(f"https://www.google.com/maps/search/{query.replace(' ', '+')}", wait_until="domcontentloaded", timeout=60000)
            await self._pause()

            # Accept cookie banner if present
            try:
                btn = page.locator('button:has-text("Accept all")')
                if await btn.first.is_visible(timeout=2000):
                    await btn.first.click()
            except Exception:
                pass

            # Collect listing URLs
            urls: list[str] = []
            seen: set[str] = set()
            no_new = 0
            try:
                await page.wait_for_selector('div[role="feed"]', timeout=10000)
            except Exception:
                await browser.close()
                return leads

            while len(urls) < max_results and no_new < 4:
                anchors = await page.query_selector_all('a[href*="/maps/place/"]')
                before = len(urls)
                for a in anchors:
                    href = await a.get_attribute("href") or ""
                    m = re.match(r"(https://www\.google\.com/maps/place/[^?]+)", href)
                    if m and m.group(1) not in seen:
                        seen.add(m.group(1)); urls.append(m.group(1))
                        if len(urls) >= max_results: break
                no_new = 0 if len(urls) > before else no_new + 1
                panel = await page.query_selector('div[role="feed"]')
                if panel:
                    await panel.evaluate("el => el.scrollBy(0, 800)")
                    await self._pause()

            # Extract each listing
            for i, url in enumerate(urls[:max_results], 1):
                lead = await self._extract(page, url)
                if lead:
                    leads.append(lead)
            await browser.close()
        return leads

    async def _extract(self, page, url: str) -> Lead | None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._pause()
            lead = Lead()
            lead.add_source(SOURCE, url)

            # Name
            el = await page.query_selector('h1.DUwDvf, h1[class*="fontHeadlineLarge"]')
            if el: lead.name = (await el.inner_text()).strip()

            # Category
            el = await page.query_selector('button[jsaction*="category"], .DkEaL')
            if el: lead.category = (await el.inner_text()).strip()

            # Rating
            el = await page.query_selector('div.F7nice span[aria-hidden="true"]')
            if el:
                try: lead.rating = float((await el.inner_text()).strip())
                except: pass

            # Reviews
            el = await page.query_selector('div.F7nice span[aria-label*="review"]')
            if el:
                label = await el.get_attribute("aria-label") or ""
                nums = re.findall(r"[\d,]+", label)
                if nums:
                    try: lead.reviews = int(nums[0].replace(",", ""))
                    except: pass

            # Address
            el = await page.query_selector('button[data-item-id="address"] .Io6YTe')
            if el:
                lead.address = (await el.inner_text()).strip()
                parts = lead.address.split(",")
                if len(parts) >= 2: lead.city = parts[-2].strip()
                if len(parts) >= 1:
                    last = parts[-1].strip().split()
                    if len(last) >= 2:
                        lead.state = last[0]
                        lead.zip_code = last[1] if len(last) > 1 else ""

            # Phone
            el = await page.query_selector('button[data-item-id*="phone"] .Io6YTe')
            if el: lead.phone = (await el.inner_text()).strip()

            # Website
            el = await page.query_selector('a[data-item-id="authority"] .Io6YTe')
            if el: lead.website = (await el.inner_text()).strip()

            # Hours
            el = await page.query_selector('div[aria-label*="hour"], button[aria-label*="hour"]')
            if el:
                label = await el.get_attribute("aria-label") or ""
                lead.hours = label.split("⋅")[0].strip() or label.split("·")[0].strip()

            return lead if lead.name else None
        except Exception:
            return None

from __future__ import annotations
"""Yellow Pages scraper (yp.com)."""
import asyncio, re
from app.models.lead_dataclass import Lead

SOURCE = "Yellow Pages"
BASE   = "https://www.yellowpages.com"


class YellowPagesScraper:
    def __init__(self, delay: float = 1.5):
        self.delay = delay

    async def _pause(self):
        import random
        await asyncio.sleep(random.uniform(self.delay * 0.8, self.delay * 1.3))

    async def scrape(self, keyword: str, location: str, max_results: int = 30, headless: bool = True) -> list[Lead]:
        from playwright.async_api import async_playwright
        leads: list[Lead] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = await ctx.new_page()

            collected: list[dict] = []   # [{url, name, ...} partial data from listing]
            page_num = 1

            while len(collected) < max_results:
                search_url = (
                    f"{BASE}/search?search_terms={keyword.replace(' ', '+')}"
                    f"&geo_location_terms={location.replace(' ', '+')}&page={page_num}"
                )
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await self._pause()

                # Cards on the search results page
                cards = await page.query_selector_all('div.result, article.srp-listing')
                if not cards:
                    break

                for card in cards:
                    try:
                        info: dict = {}
                        # Business URL
                        a = await card.query_selector('a.business-name')
                        if a:
                            info["name"] = (await a.inner_text()).strip()
                            href = await a.get_attribute("href") or ""
                            info["url"] = BASE + href if href.startswith("/") else href

                        # Phone (often visible in card)
                        ph = await card.query_selector('div.phones.phone.primary')
                        if ph: info["phone"] = (await ph.inner_text()).strip()

                        # Address
                        addr = await card.query_selector('span.street-address')
                        if addr: info["address"] = (await addr.inner_text()).strip()
                        locality = await card.query_selector('span.locality')
                        if locality:
                            loc_text = (await locality.inner_text()).strip().rstrip(",")
                            parts = loc_text.split(",")
                            info["city"] = parts[0].strip() if parts else ""
                            if len(parts) > 1:
                                sp = parts[1].strip().split()
                                info["state"]    = sp[0] if sp else ""
                                info["zip_code"] = sp[1] if len(sp) > 1 else ""

                        # Rating
                        rating_el = await card.query_selector('div.ratings span.rating')
                        if rating_el:
                            cls = await rating_el.get_attribute("class") or ""
                            m = re.search(r"rating-(\d+)", cls)
                            if m: info["rating"] = int(m.group(1)) / 10.0

                        if info.get("url"):
                            collected.append(info)
                            if len(collected) >= max_results:
                                break
                    except Exception:
                        continue

                page_num += 1
                if page_num > 10:  # safety cap
                    break

            # Build leads — YP cards have enough data without visiting each page
            for info in collected[:max_results]:
                lead = Lead()
                lead.add_source(SOURCE, info.get("url", ""))
                lead.name     = info.get("name", "")
                lead.phone    = info.get("phone", "")
                lead.address  = info.get("address", "")
                lead.city     = info.get("city", "")
                lead.state    = info.get("state", "")
                lead.zip_code = info.get("zip_code", "")
                lead.rating   = info.get("rating", 0.0)
                lead.category = keyword   # YP category = search keyword
                if lead.name:
                    leads.append(lead)

            await browser.close()
        return leads

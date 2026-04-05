"""
StepStone Germany scraper using Playwright.

StepStone is one of the largest job boards in Germany.
No official API exists — we use Playwright to interact with the site.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote_plus

from loguru import logger

from core.models import JobSchema, JobSource

STEPSTONE_BASE = "https://www.stepstone.de"
STEPSTONE_SEARCH = f"{STEPSTONE_BASE}/jobs/{{keyword}}/in-{{location}}"


def _parse_relative_date(text: str) -> Optional[datetime]:
    """Convert German relative dates like 'Vor 2 Tagen' to datetime."""
    text = text.lower().strip()
    now = datetime.now()
    if "heute" in text or "today" in text:
        return now
    if "gestern" in text or "yesterday" in text:
        return now - timedelta(days=1)
    match = re.search(r"(\d+)\s*tag", text)
    if match:
        return now - timedelta(days=int(match.group(1)))
    match = re.search(r"(\d+)\s*stund", text)
    if match:
        return now - timedelta(hours=int(match.group(1)))
    return None


async def scrape_stepstone(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """
    Scrape StepStone job listings using Playwright.
    Handles German GDPR cookie banners automatically.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed. Run: pip install playwright && playwright install")
        return []

    if locations is None:
        locations = ["Deutschland"]

    all_jobs: List[JobSchema] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="de-DE",
            timezone_id="Europe/Berlin",
        )
        page = await context.new_page()

        for position in positions:
            for location in locations:
                logger.info(f"[StepStone] Scraping '{position}' in '{location}'")

                url = (
                    f"{STEPSTONE_BASE}/jobs/{quote_plus(position)}"
                    f"/in-{quote_plus(location)}?radius=50"
                )

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                    # Handle GDPR cookie consent banner
                    await _dismiss_cookie_banner(page)

                    await page.wait_for_timeout(2000)
                    collected = 0

                    while collected < max_results:
                        job_cards = await page.query_selector_all(
                            "article[data-at='job-item'], [data-testid='job-item']"
                        )

                        if not job_cards:
                            # Try alternative selectors
                            job_cards = await page.query_selector_all(
                                ".res-1r9oqkj, [class*='JobCard'], article.sc-"
                            )

                        logger.debug(f"[StepStone] Found {len(job_cards)} cards on page")

                        for card in job_cards:
                            if collected >= max_results:
                                break
                            job = await _parse_card(card, page)
                            if job:
                                all_jobs.append(job)
                                collected += 1

                        # Try to click "Load more" or go to next page
                        next_loaded = await _load_more(page)
                        if not next_loaded:
                            break

                        await page.wait_for_timeout(1500)

                except Exception as e:
                    logger.error(f"[StepStone] Error scraping '{position}' @ '{location}': {e}")

        await browser.close()

    logger.info(f"[StepStone] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _dismiss_cookie_banner(page) -> None:
    """Dismiss GDPR cookie consent banners common on German sites."""
    selectors = [
        "button#onetrust-accept-btn-handler",
        "button[data-testid='cookie-accept-all']",
        "button.cookie-accept",
        "[id*='accept'][id*='cookie']",
        "[class*='cookie'][class*='accept']",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Zustimmen')",
    ]
    for selector in selectors:
        try:
            btn = await page.wait_for_selector(selector, timeout=3000)
            if btn:
                await btn.click()
                await page.wait_for_timeout(500)
                logger.debug("[StepStone] Cookie banner dismissed")
                return
        except Exception:
            continue


async def _parse_card(card, page) -> Optional[JobSchema]:
    """Extract job data from a StepStone job card element."""
    try:
        # Title
        title_el = await card.query_selector(
            "[data-at='job-item-title'], h2 a, .res-nehv70, [class*='JobTitle']"
        )
        title = await title_el.inner_text() if title_el else ""
        title = title.strip()
        if not title:
            return None

        # Company
        company_el = await card.query_selector(
            "[data-at='job-item-company-name'], [class*='CompanyName'], [data-testid='company-name']"
        )
        company = await company_el.inner_text() if company_el else "Unknown"
        company = company.strip()

        # Location
        location_el = await card.query_selector(
            "[data-at='job-item-location'], [class*='Location'], [data-testid='location']"
        )
        location = await location_el.inner_text() if location_el else ""
        location = location.strip()

        # URL
        link_el = await card.query_selector("a[href*='/stellenangebote/'], a[href*='/jobs/']")
        href = await link_el.get_attribute("href") if link_el else None
        if not href:
            link_el = await card.query_selector("a")
            href = await link_el.get_attribute("href") if link_el else None

        job_url = href if href and href.startswith("http") else (
            f"https://www.stepstone.de{href}" if href else ""
        )
        if not job_url:
            return None

        # Date
        date_el = await card.query_selector("[data-at='job-item-date'], time, [class*='Date']")
        date_text = await date_el.inner_text() if date_el else ""
        date_posted = _parse_relative_date(date_text)

        # Remote
        card_text = await card.inner_text()
        is_remote = any(
            kw in card_text.lower()
            for kw in ["remote", "homeoffice", "home office", "mobiles arbeiten"]
        )

        return JobSchema(
            source=JobSource.STEPSTONE,
            title=title,
            company=company,
            location=location,
            is_remote=is_remote,
            url=job_url,
            date_posted=date_posted,
        )
    except Exception as e:
        logger.debug(f"[StepStone] Card parse error: {e}")
        return None


async def _load_more(page) -> bool:
    """Try to load more results. Returns True if more were loaded."""
    selectors = [
        "button[data-at='load-more']",
        "button:has-text('Mehr laden')",
        "button:has-text('Weitere Ergebnisse')",
        "a[data-at='pagination-next']",
        "[aria-label='Nächste Seite']",
    ]
    for selector in selectors:
        try:
            btn = await page.wait_for_selector(selector, timeout=2000)
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(2000)
                return True
        except Exception:
            continue
    return False


async def scrape_stepstone_job_detail(url: str, headless: bool = True) -> Optional[str]:
    """Fetch full job description from a StepStone job detail page."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await _dismiss_cookie_banner(page)
            await page.wait_for_timeout(1000)

            desc_el = await page.query_selector(
                "[data-at='job-ad-overview'], .listing--jobdetails, "
                "[class*='JobDescription'], article"
            )
            text = await desc_el.inner_text() if desc_el else await page.inner_text("body")
            return text.strip()
        finally:
            await browser.close()

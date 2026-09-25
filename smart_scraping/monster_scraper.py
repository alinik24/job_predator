"""
Monster.de scraper using Playwright.

Monster is one of the major international job boards with strong Germany presence.
No official API — uses Playwright browser automation.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote_plus

from loguru import logger

from core.models import JobSchema, JobSource

MONSTER_BASE = "https://www.monster.de"
MONSTER_SEARCH = f"{MONSTER_BASE}/jobs/suche/"


def _parse_relative_date(text: str) -> Optional[datetime]:
    text = text.lower().strip()
    now = datetime.now()
    if "heute" in text or "today" in text:
        return now
    if "gestern" in text or "yesterday" in text:
        return now - timedelta(days=1)
    match = re.search(r"(\d+)\s*tag", text)
    if match:
        return now - timedelta(days=int(match.group(1)))
    return None


async def scrape_monster(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """Scrape Monster.de job listings using Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed.")
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
                logger.info(f"[Monster] Scraping '{position}' in '{location}'")

                url = (
                    f"{MONSTER_SEARCH}?q={quote_plus(position)}"
                    f"&where={quote_plus(location)}&cy=de"
                )

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await _dismiss_cookie_banner(page)
                    await page.wait_for_timeout(2000)

                    collected = 0
                    while collected < max_results:
                        # Monster job card selectors
                        cards = await page.query_selector_all(
                            "[data-testid='jobCard'], .job-search-resultsstyle__JobCard, "
                            "article.job-card, [class*='job-result']"
                        )

                        if not cards:
                            cards = await page.query_selector_all(
                                "section[data-jobid], div[data-jobid]"
                            )

                        logger.debug(f"[Monster] Found {len(cards)} cards")

                        for card in cards:
                            if collected >= max_results:
                                break
                            job = await _parse_card(card)
                            if job:
                                all_jobs.append(job)
                                collected += 1

                        # Try next page
                        next_btn = await page.query_selector(
                            "[data-testid='pagination-next'], a[aria-label='Nächste Seite'], "
                            "a.pagination-next, [class*='pagination'] a[rel='next']"
                        )
                        if not next_btn or collected >= max_results:
                            break

                        await next_btn.click()
                        await page.wait_for_timeout(2000)

                except Exception as e:
                    logger.error(f"[Monster] Error scraping '{position}' @ '{location}': {e}")

        await browser.close()

    logger.info(f"[Monster] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _dismiss_cookie_banner(page) -> None:
    selectors = [
        "button#onetrust-accept-btn-handler",
        "button[id*='accept']",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Zustimmen')",
        "[class*='cookie'] button[class*='accept']",
    ]
    for selector in selectors:
        try:
            btn = await page.wait_for_selector(selector, timeout=3000)
            if btn:
                await btn.click()
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


async def _parse_card(card) -> Optional[JobSchema]:
    try:
        title_el = await card.query_selector(
            "[data-testid='jobTitle'], h2, h3, [class*='title']"
        )
        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title:
            return None

        company_el = await card.query_selector(
            "[data-testid='company'], [class*='company'], [class*='employer']"
        )
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        location_el = await card.query_selector(
            "[data-testid='location'], [class*='location'], [class*='city']"
        )
        location = (await location_el.inner_text()).strip() if location_el else ""

        link_el = await card.query_selector("a[href*='/job'], a[href*='/stelle']")
        if not link_el:
            link_el = await card.query_selector("a")
        href = await link_el.get_attribute("href") if link_el else None
        job_url = href if href and href.startswith("http") else (
            f"https://www.monster.de{href}" if href else ""
        )
        if not job_url:
            return None

        date_el = await card.query_selector("time, [class*='date'], [class*='posted']")
        date_text = (await date_el.inner_text()).strip() if date_el else ""
        date_posted = _parse_relative_date(date_text)

        card_text = await card.inner_text()
        is_remote = any(
            kw in card_text.lower()
            for kw in ["remote", "homeoffice", "home office", "mobiles arbeiten"]
        )

        return JobSchema(
            source=JobSource.MONSTER,
            title=title,
            company=company,
            location=location,
            is_remote=is_remote,
            url=job_url,
            date_posted=date_posted,
        )
    except Exception as e:
        logger.debug(f"[Monster] Card parse error: {e}")
        return None

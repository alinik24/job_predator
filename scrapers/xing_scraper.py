"""
XING job scraper using Playwright.

XING (now part of New Work SE) is a major professional network in Germany.
No public API — Playwright with login required for full access.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote_plus

from loguru import logger

from core.config import settings
from core.models import JobSchema, JobSource

XING_BASE = "https://www.xing.com"
XING_JOBS_URL = f"{XING_BASE}/jobs/search"


async def scrape_xing(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """
    Scrape XING job listings.
    If XING credentials are configured, logs in for better access.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed")
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
        )
        page = await context.new_page()

        # Login if credentials are available
        logged_in = False
        if settings.xing_email and settings.xing_password:
            logged_in = await _xing_login(page, settings.xing_email, settings.xing_password)

        for position in positions:
            for location in locations:
                logger.info(f"[XING] Scraping '{position}' in '{location}'")
                try:
                    url = (
                        f"{XING_JOBS_URL}?keywords={quote_plus(position)}"
                        f"&location={quote_plus(location)}&radius=50"
                    )
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await _dismiss_cookie_banner(page)
                    await page.wait_for_timeout(2000)

                    collected = 0
                    while collected < max_results:
                        cards = await page.query_selector_all(
                            "[data-testid='job-posting-card'], "
                            ".job-posting-card, "
                            "[class*='JobTeaserDesktop']"
                        )

                        logger.debug(f"[XING] Found {len(cards)} cards")

                        for card in cards:
                            if collected >= max_results:
                                break
                            job = await _parse_xing_card(card)
                            if job:
                                all_jobs.append(job)
                                collected += 1

                        if not await _next_page_xing(page):
                            break

                        await page.wait_for_timeout(2000)

                except Exception as e:
                    logger.error(f"[XING] Error: {e}")

        await browser.close()

    logger.info(f"[XING] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _xing_login(page, email: str, password: str) -> bool:
    """Attempt to log in to XING."""
    try:
        await page.goto(f"{XING_BASE}/login", wait_until="domcontentloaded", timeout=20000)
        await _dismiss_cookie_banner(page)

        await page.fill("input[name='email'], input[type='email']", email)
        await page.fill("input[name='password'], input[type='password']", password)
        await page.click("button[type='submit'], button:has-text('Einloggen')")
        await page.wait_for_timeout(3000)

        # Check if login succeeded
        if "jobs" in page.url or "dashboard" in page.url or "newsfeed" in page.url:
            logger.info("[XING] Login successful")
            return True
        logger.warning("[XING] Login may have failed")
        return False
    except Exception as e:
        logger.error(f"[XING] Login error: {e}")
        return False


async def _dismiss_cookie_banner(page) -> None:
    selectors = [
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button[data-testid='accept-all-cookies']",
        "#onetrust-accept-btn-handler",
        "button.cookie-consent__btn--accept",
    ]
    for selector in selectors:
        try:
            btn = await page.wait_for_selector(selector, timeout=2000)
            if btn:
                await btn.click()
                await page.wait_for_timeout(300)
                return
        except Exception:
            continue


async def _parse_xing_card(card) -> Optional[JobSchema]:
    try:
        title_el = await card.query_selector(
            "[data-testid='job-posting-title'], h2, h3, [class*='title']"
        )
        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title:
            return None

        company_el = await card.query_selector(
            "[data-testid='company-name'], [class*='company'], [class*='Company']"
        )
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        location_el = await card.query_selector(
            "[data-testid='job-posting-location'], [class*='location'], [class*='Location']"
        )
        location = (await location_el.inner_text()).strip() if location_el else ""

        link_el = await card.query_selector("a[href*='/jobs/'], a")
        href = await link_el.get_attribute("href") if link_el else None
        job_url = (
            href if href and href.startswith("http")
            else f"https://www.xing.com{href}" if href
            else ""
        )
        if not job_url:
            return None

        card_text = await card.inner_text()
        is_remote = any(
            kw in card_text.lower()
            for kw in ["remote", "homeoffice", "home office", "mobiles arbeiten"]
        )

        return JobSchema(
            source=JobSource.XING,
            title=title,
            company=company,
            location=location,
            is_remote=is_remote,
            url=job_url,
        )
    except Exception as e:
        logger.debug(f"[XING] Card parse error: {e}")
        return None


async def _next_page_xing(page) -> bool:
    selectors = [
        "button[aria-label='Nächste Seite']",
        "a[aria-label='Next page']",
        "button:has-text('Weiter')",
        "[data-testid='pagination-next']",
    ]
    for selector in selectors:
        try:
            btn = await page.wait_for_selector(selector, timeout=1500)
            if btn and await btn.is_visible() and await btn.is_enabled():
                await btn.click()
                return True
        except Exception:
            continue
    return False

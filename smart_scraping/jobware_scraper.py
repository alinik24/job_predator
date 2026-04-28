"""
Jobware.de scraper — German mid-to-senior job board with strong IT/Engineering focus.

Jobware has a basic search API endpoint that returns JSON — no auth required.
Docs: https://api.jobware.de (undocumented public endpoint)
Fallback: Playwright if API fails.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote_plus

import httpx
from loguru import logger

from core.models import JobSchema, JobSource

JOBWARE_API = "https://api.jobware.de/api/v1/search"
JOBWARE_BASE = "https://www.jobware.de"


async def scrape_jobware(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """
    Scrape Jobware.de. Tries HTTP API first, falls back to Playwright.
    """
    if locations is None:
        locations = ["Deutschland"]

    all_jobs: List[JobSchema] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html, */*",
            "Referer": "https://www.jobware.de/",
        },
        follow_redirects=True,
        timeout=30,
    ) as client:
        for position in positions:
            for location in locations:
                logger.info(f"[Jobware] Scraping '{position}' in '{location}'")

                # Try Jobware search URL (HTML parsing)
                try:
                    jobs = await _scrape_via_search(client, position, location, max_results)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(f"[Jobware] HTTP search failed: {e}, trying Playwright...")
                    try:
                        jobs = await _scrape_via_playwright(
                            position, location, max_results, headless
                        )
                        all_jobs.extend(jobs)
                    except Exception as e2:
                        logger.error(f"[Jobware] Playwright also failed: {e2}")

                await asyncio.sleep(1)

    logger.info(f"[Jobware] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _scrape_via_search(
    client: httpx.AsyncClient,
    position: str,
    location: str,
    max_results: int,
) -> List[JobSchema]:
    """Parse Jobware search results page using BeautifulSoup."""
    from bs4 import BeautifulSoup

    jobs = []
    page = 1
    collected = 0

    while collected < max_results:
        url = (
            f"{JOBWARE_BASE}/suche/{quote_plus(position)}"
            f"?lo={quote_plus(location)}&page={page}"
        )
        resp = await client.get(url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Jobware uses article tags with class "jobpost" or similar
        cards = soup.find_all("article", class_=lambda c: c and "job" in c.lower())
        if not cards:
            cards = soup.find_all("div", attrs={"data-jobid": True})
        if not cards:
            # Generic fallback
            cards = soup.find_all("li", class_=lambda c: c and "result" in (c or "").lower())

        if not cards:
            break

        for card in cards:
            if collected >= max_results:
                break

            job = _parse_bs_card(card)
            if job:
                jobs.append(job)
                collected += 1

        # Check for next page
        next_link = soup.find("a", attrs={"rel": "next"}) or soup.find(
            "a", string=lambda s: s and ("weiter" in s.lower() or "nächste" in s.lower())
        )
        if not next_link:
            break
        page += 1

    return jobs


def _parse_bs_card(card) -> Optional[JobSchema]:
    try:
        title_el = card.find(["h2", "h3", "h1"]) or card.find(class_=lambda c: c and "title" in (c or "").lower())
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        link_el = card.find("a", href=True)
        href = link_el["href"] if link_el else ""
        job_url = href if href.startswith("http") else f"{JOBWARE_BASE}{href}" if href else ""
        if not job_url:
            return None

        company_el = card.find(class_=lambda c: c and "company" in (c or "").lower()) or \
                     card.find(class_=lambda c: c and "arbeit" in (c or "").lower())
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        location_el = card.find(class_=lambda c: c and ("location" in (c or "").lower() or "ort" in (c or "").lower()))
        location = location_el.get_text(strip=True) if location_el else ""

        card_text = card.get_text().lower()
        is_remote = any(kw in card_text for kw in ["remote", "homeoffice", "home office"])

        return JobSchema(
            source=JobSource.JOBWARE,
            title=title,
            company=company,
            location=location,
            is_remote=is_remote,
            url=job_url,
        )
    except Exception as e:
        logger.debug(f"[Jobware] BS card parse error: {e}")
        return None


async def _scrape_via_playwright(
    position: str,
    location: str,
    max_results: int,
    headless: bool,
) -> List[JobSchema]:
    from playwright.async_api import async_playwright

    jobs = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(locale="de-DE", timezone_id="Europe/Berlin")
        page = await context.new_page()

        url = f"{JOBWARE_BASE}/suche/{quote_plus(position)}?lo={quote_plus(location)}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Cookie banner
        for sel in ["button:has-text('Alle akzeptieren')", "button:has-text('Akzeptieren')",
                    "button#onetrust-accept-btn-handler"]:
            try:
                btn = await page.wait_for_selector(sel, timeout=3000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await page.wait_for_timeout(2000)

        cards = await page.query_selector_all("article, [data-jobid], .jobpost")
        for card in cards[:max_results]:
            try:
                title_el = await card.query_selector("h2, h3, [class*='title']")
                title = (await title_el.inner_text()).strip() if title_el else ""
                if not title:
                    continue

                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                job_url = href if href.startswith("http") else f"{JOBWARE_BASE}{href}" if href else ""
                if not job_url:
                    continue

                company_el = await card.query_selector("[class*='company'], [class*='employer']")
                company = (await company_el.inner_text()).strip() if company_el else "Unknown"

                location_el = await card.query_selector("[class*='location'], [class*='city']")
                location_text = (await location_el.inner_text()).strip() if location_el else ""

                jobs.append(JobSchema(
                    source=JobSource.JOBWARE,
                    title=title,
                    company=company,
                    location=location_text,
                    url=job_url,
                ))
            except Exception:
                continue

        await browser.close()

    return jobs

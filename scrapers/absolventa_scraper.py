"""
Absolventa scraper — German job board focused on graduates, young professionals,
and entry-level positions. Strong in tech and engineering.

Method: HTTP + BeautifulSoup + JSON-LD. Falls back to Playwright.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from core.models import JobSchema, JobSource

ABSOLVENTA_BASE = "https://www.absolventa.de"
ABSOLVENTA_SEARCH = f"{ABSOLVENTA_BASE}/jobs"


async def scrape_absolventa(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """Scrape Absolventa.de for graduate and junior positions."""
    if locations is None:
        locations = [""]

    all_jobs: List[JobSchema] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-DE,de;q=0.9",
        },
        follow_redirects=True,
        timeout=30,
    ) as client:
        for position in positions:
            for location in locations:
                logger.info(f"[Absolventa] Scraping '{position}' in '{location or 'DE'}'")
                try:
                    jobs = await _fetch_jobs(client, position, location, max_results)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(f"[Absolventa] HTTP failed ({e}), trying Playwright...")
                    try:
                        jobs = await _scrape_playwright(position, location, max_results, headless)
                        all_jobs.extend(jobs)
                    except Exception as e2:
                        logger.error(f"[Absolventa] All methods failed: {e2}")
                await asyncio.sleep(1)

    logger.info(f"[Absolventa] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _fetch_jobs(
    client: httpx.AsyncClient,
    position: str,
    location: str,
    max_results: int,
) -> List[JobSchema]:
    jobs = []
    page = 1

    while len(jobs) < max_results:
        params: dict = {"q": position, "page": page}
        if location:
            params["location"] = location

        resp = await client.get(ABSOLVENTA_SEARCH, params=params)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "JobPosting" and len(jobs) < max_results:
                        job = _parse_jsonld(item)
                        if job:
                            jobs.append(job)
            except Exception:
                pass

        if jobs:
            break

        # HTML fallback
        cards = (
            soup.find_all("article", class_=lambda c: c and "job" in (c or "").lower())
            or soup.find_all("div", class_="job-teaser")
            or soup.find_all("li", class_=lambda c: c and "job" in (c or "").lower())
        )
        if not cards:
            break

        for card in cards:
            if len(jobs) >= max_results:
                break
            job = _parse_card(card)
            if job:
                jobs.append(job)

        next_link = soup.find("a", attrs={"rel": "next"})
        if not next_link:
            break
        page += 1

    return jobs


def _parse_jsonld(data: dict) -> Optional[JobSchema]:
    try:
        title = data.get("title", "")
        if not title:
            return None
        url = data.get("url") or data.get("@id", "")
        company = ""
        org = data.get("hiringOrganization", {})
        if isinstance(org, dict):
            company = org.get("name", "Unknown")
        location = ""
        loc = data.get("jobLocation", {})
        if isinstance(loc, dict):
            addr = loc.get("address", {})
            if isinstance(addr, dict):
                location = addr.get("addressLocality", "")
        date_posted = None
        dp = data.get("datePosted")
        if dp:
            try:
                date_posted = datetime.fromisoformat(dp[:10])
            except Exception:
                pass
        return JobSchema(
            source=JobSource.ABSOLVENTA,
            title=title,
            company=company,
            location=location,
            url=url,
            date_posted=date_posted,
        )
    except Exception:
        return None


def _parse_card(card) -> Optional[JobSchema]:
    try:
        title_el = card.find("h2") or card.find("h3") or card.find("a", class_=lambda c: c and "title" in (c or "").lower())
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        link_el = card.find("a", href=True)
        href = link_el["href"] if link_el else ""
        job_url = href if href.startswith("http") else f"{ABSOLVENTA_BASE}{href}" if href else ""
        if not job_url:
            return None

        company_el = card.find(class_=lambda c: c and "company" in (c or "").lower())
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        location_el = card.find(class_=lambda c: c and "location" in (c or "").lower())
        location = location_el.get_text(strip=True) if location_el else ""

        return JobSchema(
            source=JobSource.ABSOLVENTA,
            title=title,
            company=company,
            location=location,
            url=job_url,
        )
    except Exception as e:
        logger.debug(f"[Absolventa] Card parse error: {e}")
        return None


async def _scrape_playwright(
    position: str,
    location: str,
    max_results: int,
    headless: bool,
) -> List[JobSchema]:
    from playwright.async_api import async_playwright

    jobs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = await browser.new_context(locale="de-DE")
        page = await context.new_page()

        params = f"?q={quote_plus(position)}"
        if location:
            params += f"&location={quote_plus(location)}"
        await page.goto(f"{ABSOLVENTA_SEARCH}{params}", wait_until="domcontentloaded", timeout=30000)

        for sel in ["button:has-text('Alle akzeptieren')", "button#onetrust-accept-btn-handler"]:
            try:
                btn = await page.wait_for_selector(sel, timeout=3000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await page.wait_for_timeout(2000)

        # Extract JSON-LD
        content = await page.content()
        soup = BeautifulSoup(content, "lxml")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "JobPosting" and len(jobs) < max_results:
                        job = _parse_jsonld(item)
                        if job:
                            jobs.append(job)
            except Exception:
                pass

        await browser.close()

    return jobs

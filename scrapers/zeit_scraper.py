"""
Zeit Jobs scraper — academic, research and senior professional jobs.

jobs.zeit.de is the job board of Die Zeit, Germany's most prestigious
weekly newspaper. It specialises in highly qualified positions:
academics, researchers, doctors, engineers, and public-sector roles.
Strong for postdoc, research associate, and data scientist roles.

Method: HTTP + BeautifulSoup (server-side rendered with JSON-LD).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from core.models import JobSchema, JobSource

ZEIT_BASE = "https://jobs.zeit.de"
ZEIT_SEARCH = f"{ZEIT_BASE}/stellenangebote"


async def scrape_zeit(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """Scrape Zeit Jobs for research and academic positions."""
    all_jobs: List[JobSchema] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-DE,de;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
        follow_redirects=True,
        timeout=30,
    ) as client:
        locs = locations or [""]
        for position in positions:
            for location in locs:
                logger.info(f"[Zeit] Scraping '{position}' in '{location or 'Deutschland'}'")
                try:
                    jobs = await _fetch_jobs(client, position, location, max_results)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(f"[Zeit] HTTP failed ({e}), trying Playwright...")
                    try:
                        jobs = await _scrape_playwright(position, location, max_results, headless)
                        all_jobs.extend(jobs)
                    except Exception as e2:
                        logger.error(f"[Zeit] All methods failed: {e2}")
                await asyncio.sleep(1.5)

    logger.info(f"[Zeit] Total collected: {len(all_jobs)} jobs")
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

        resp = await client.get(ZEIT_SEARCH, params=params)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else data.get("itemListElement", [data])
                for item in items:
                    item = item.get("item", item) if isinstance(item, dict) else item
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        job = _parse_jsonld(item)
                        if job:
                            jobs.append(job)
                if jobs:
                    break
            except Exception:
                pass

        if jobs:
            break

        # HTML fallback
        cards = (
            soup.find_all("article", class_=lambda c: c and "job" in (c or "").lower())
            or soup.find_all("div", class_=lambda c: c and any(
                kw in (c or "").lower() for kw in ["job-item", "job-result", "stellenangebot"]
            ))
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

        next_link = soup.find("a", attrs={"rel": "next"}) or soup.find(
            "a", string=lambda s: s and "weiter" in (s or "").lower()
        )
        if not next_link:
            break
        page += 1

    return jobs


def _parse_card(card) -> Optional[JobSchema]:
    try:
        title_el = (
            card.find("h2") or card.find("h3") or card.find("h4")
            or card.find(class_=lambda c: c and "title" in (c or "").lower())
        )
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        link_el = card.find("a", href=True)
        href = link_el["href"] if link_el else ""
        job_url = href if href.startswith("http") else urljoin(ZEIT_BASE, href) if href else ""
        if not job_url:
            return None

        company_el = card.find(class_=lambda c: c and any(
            kw in (c or "").lower() for kw in ["company", "employer", "arbeitgeber", "institution"]
        ))
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        location_el = card.find(class_=lambda c: c and ("location" in (c or "").lower() or "ort" in (c or "").lower()))
        location = location_el.get_text(strip=True) if location_el else "Deutschland"

        return JobSchema(
            source=JobSource.ZEIT_JOBS,
            title=title,
            company=company,
            location=location,
            url=job_url,
        )
    except Exception as e:
        logger.debug(f"[Zeit] Card parse error: {e}")
        return None


def _parse_jsonld(data: dict) -> Optional[JobSchema]:
    try:
        title = data.get("title", "")
        if not title:
            return None
        url = data.get("url") or data.get("@id", "")
        org = data.get("hiringOrganization", {})
        company = org.get("name", "Unknown") if isinstance(org, dict) else "Unknown"
        loc = data.get("jobLocation", {})
        location = ""
        if isinstance(loc, dict):
            addr = loc.get("address", {})
            if isinstance(addr, dict):
                location = addr.get("addressLocality") or addr.get("addressCountry", "Deutschland")
        date_posted = None
        dp = data.get("datePosted", "")
        if dp:
            try:
                date_posted = datetime.fromisoformat(dp[:10])
            except ValueError:
                pass
        return JobSchema(
            source=JobSource.ZEIT_JOBS,
            title=title,
            company=company,
            location=location or "Deutschland",
            url=url,
            date_posted=date_posted,
            description=(data.get("description", "") or "")[:2000] or None,
        )
    except Exception:
        return None


async def _scrape_playwright(
    position: str,
    location: str,
    max_results: int,
    headless: bool,
) -> List[JobSchema]:
    from playwright.async_api import async_playwright

    jobs = []
    url = f"{ZEIT_SEARCH}?q={quote_plus(position)}"
    if location:
        url += f"&location={quote_plus(location)}"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = await browser.new_context(locale="de-DE")
        page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        for sel in ["button:has-text('Alle akzeptieren')", "button:has-text('Akzeptieren')",
                    "#onetrust-accept-btn-handler"]:
            try:
                btn = await page.wait_for_selector(sel, timeout=3000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await page.wait_for_timeout(2000)

        cards = await page.query_selector_all(
            "article, [class*='job-item'], [class*='job-result'], li[class*='job']"
        )

        for card in cards[:max_results]:
            try:
                title_el = await card.query_selector("h2, h3, h4, [class*='title']")
                title = (await title_el.inner_text()).strip() if title_el else ""
                if not title:
                    continue

                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                job_url = href if (href or "").startswith("http") else urljoin(ZEIT_BASE, href) if href else ""
                if not job_url:
                    continue

                company_el = await card.query_selector("[class*='company'], [class*='employer']")
                company = (await company_el.inner_text()).strip() if company_el else "Unknown"

                location_el = await card.query_selector("[class*='location']")
                loc = (await location_el.inner_text()).strip() if location_el else "Deutschland"

                jobs.append(JobSchema(
                    source=JobSource.ZEIT_JOBS,
                    title=title,
                    company=company,
                    location=loc,
                    url=job_url,
                ))
            except Exception:
                continue

        await browser.close()

    return jobs

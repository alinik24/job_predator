"""
Fraunhofer Institute scraper — applied research jobs in Germany.

Fraunhofer-Gesellschaft is Germany's largest applied research organisation,
with 76 institutes. Their unified job portal at jobs.fraunhofer.de lists
all positions: working students, thesis students, research engineers,
postdocs, and permanent staff.

Extremely relevant for energy/AI/data engineering candidates.

Method: HTTP + BeautifulSoup (server-side rendered / JSON-LD).
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

FRAUNHOFER_BASE = "https://jobs.fraunhofer.de"
FRAUNHOFER_SEARCH = f"{FRAUNHOFER_BASE}/search"


async def scrape_fraunhofer(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """Scrape Fraunhofer job portal for research and engineering positions."""
    all_jobs: List[JobSchema] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
        follow_redirects=True,
        timeout=30,
    ) as client:
        locs = locations or [""]
        for position in positions:
            for location in locs:
                logger.info(f"[Fraunhofer] Scraping '{position}' in '{location or 'Deutschland'}'")
                try:
                    jobs = await _fetch_jobs(client, position, location, max_results)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(f"[Fraunhofer] HTTP failed ({e}), trying Playwright...")
                    try:
                        jobs = await _scrape_playwright(position, location, max_results, headless)
                        all_jobs.extend(jobs)
                    except Exception as e2:
                        logger.error(f"[Fraunhofer] All methods failed: {e2}")
                await asyncio.sleep(1.5)

    logger.info(f"[Fraunhofer] Total collected: {len(all_jobs)} jobs")
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
        params: dict = {
            "q": position,
            "page": page,
        }
        if location:
            params["location"] = location

        resp = await client.get(FRAUNHOFER_SEARCH, params=params)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Try JSON-LD first (Fraunhofer uses schema.org JobPosting)
        jsonld_jobs = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "JobPosting":
                        job = _parse_jsonld(item)
                        if job:
                            jsonld_jobs.append(job)
            except Exception:
                pass
        if jsonld_jobs:
            jobs.extend(jsonld_jobs[:max_results - len(jobs)])
            break

        # HTML card fallback
        cards = (
            soup.find_all("article", class_=lambda c: c and "job" in (c or "").lower())
            or soup.find_all("div", class_=lambda c: c and any(
                kw in (c or "").lower() for kw in ["job-item", "job-card", "job-listing", "result-item"]
            ))
            or soup.find_all("li", class_=lambda c: c and "job" in (c or "").lower())
            or soup.find_all("div", class_="searchResultItem")
        )

        if not cards:
            break

        for card in cards:
            if len(jobs) >= max_results:
                break
            job = _parse_card(card)
            if job:
                jobs.append(job)

        next_link = (
            soup.find("a", attrs={"rel": "next"})
            or soup.find("a", string=lambda s: s and ("weiter" in (s or "").lower() or "next" in (s or "").lower()))
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
        job_url = href if href.startswith("http") else urljoin(FRAUNHOFER_BASE, href) if href else ""
        if not job_url:
            return None

        company_el = card.find(class_=lambda c: c and any(
            kw in (c or "").lower() for kw in ["institute", "employer", "company", "department"]
        ))
        company = company_el.get_text(strip=True) if company_el else "Fraunhofer-Gesellschaft"
        if not company or company == company_el:
            company = "Fraunhofer-Gesellschaft"

        location_el = card.find(class_=lambda c: c and "location" in (c or "").lower())
        location = location_el.get_text(strip=True) if location_el else "Deutschland"

        date_el = card.find(class_=lambda c: c and any(
            kw in (c or "").lower() for kw in ["date", "posted", "datum"]
        ))
        date_posted = None
        if date_el:
            date_text = date_el.get_text(strip=True)
            for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
                try:
                    date_posted = datetime.strptime(date_text[:10], fmt)
                    break
                except ValueError:
                    continue

        return JobSchema(
            source=JobSource.FRAUNHOFER,
            title=title,
            company=company,
            location=location,
            url=job_url,
            date_posted=date_posted,
        )
    except Exception as e:
        logger.debug(f"[Fraunhofer] Card parse error: {e}")
        return None


def _parse_jsonld(data: dict) -> Optional[JobSchema]:
    try:
        title = data.get("title", "")
        if not title:
            return None
        url = data.get("url") or data.get("@id", "")
        org = data.get("hiringOrganization", {})
        company = org.get("name", "Fraunhofer-Gesellschaft") if isinstance(org, dict) else "Fraunhofer-Gesellschaft"
        loc = data.get("jobLocation", {})
        location = ""
        if isinstance(loc, dict):
            addr = loc.get("address", {})
            if isinstance(addr, dict):
                location = (
                    addr.get("addressLocality")
                    or addr.get("addressRegion")
                    or addr.get("addressCountry", "Deutschland")
                )
        date_posted = None
        dp = data.get("datePosted", "")
        if dp:
            try:
                date_posted = datetime.fromisoformat(dp[:10])
            except ValueError:
                pass
        desc = data.get("description", "")
        return JobSchema(
            source=JobSource.FRAUNHOFER,
            title=title,
            company=company,
            location=location or "Deutschland",
            url=url,
            date_posted=date_posted,
            description=desc[:2000] if desc else None,
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
    url = f"{FRAUNHOFER_SEARCH}?q={quote_plus(position)}"
    if location:
        url += f"&location={quote_plus(location)}"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = await browser.new_context(locale="de-DE")
        page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        for sel in [
            "button:has-text('Alle akzeptieren')",
            "button:has-text('Akzeptieren')",
            "button#onetrust-accept-btn-handler",
            "button[id*='accept']",
        ]:
            try:
                btn = await page.wait_for_selector(sel, timeout=3000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await page.wait_for_timeout(2000)

        cards = await page.query_selector_all(
            "article, [class*='job-item'], [class*='job-card'], [class*='result-item'], li[class*='job']"
        )

        for card in cards[:max_results]:
            try:
                title_el = await card.query_selector("h2, h3, h4, [class*='title']")
                title = (await title_el.inner_text()).strip() if title_el else ""
                if not title:
                    continue

                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                job_url = href if (href or "").startswith("http") else urljoin(FRAUNHOFER_BASE, href) if href else ""
                if not job_url:
                    continue

                company_el = await card.query_selector(
                    "[class*='institute'], [class*='company'], [class*='employer']"
                )
                company = (await company_el.inner_text()).strip() if company_el else "Fraunhofer-Gesellschaft"

                location_el = await card.query_selector("[class*='location']")
                loc = (await location_el.inner_text()).strip() if location_el else "Deutschland"

                jobs.append(JobSchema(
                    source=JobSource.FRAUNHOFER,
                    title=title,
                    company=company,
                    location=loc,
                    url=job_url,
                ))
            except Exception:
                continue

        await browser.close()

    return jobs

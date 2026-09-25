"""
Helmholtz Association scraper — large-scale German research infrastructure.

Helmholtz (helmholtz.de) is Germany's largest scientific organisation with
18 research centres and 43 000 employees. Covers energy, health, earth,
aeronautics, key technologies, and matter research.

Relevant centres for energy/AI candidates:
  - FZJ (Forschungszentrum Jülich) — energy systems, supercomputing
  - DLR — aerospace, energy, transport
  - KIT — Karlsruhe Institute of Technology
  - DKFZ — German Cancer Research Center
  - HZB — Berlin, renewable energy materials

Method: HTTP + BeautifulSoup. Falls back to Playwright.
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

HELMHOLTZ_BASE = "https://www.helmholtz.de"
HELMHOLTZ_JOBS = f"{HELMHOLTZ_BASE}/en/career/job-offers"
# FZJ has its own unified board — most relevant for energy/AI
FZJ_JOBS = "https://www.fz-juelich.de/en/careers/jobs-and-training"


async def scrape_helmholtz(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """Scrape Helmholtz Association job portal."""
    all_jobs: List[JobSchema] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-GB,en;q=0.9,de;q=0.8",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
        follow_redirects=True,
        timeout=30,
    ) as client:
        for position in positions:
            logger.info(f"[Helmholtz] Scraping '{position}'")
            try:
                jobs = await _fetch_jobs(client, position, max_results)
                all_jobs.extend(jobs)
            except Exception as e:
                logger.warning(f"[Helmholtz] HTTP failed ({e}), trying Playwright...")
                try:
                    jobs = await _scrape_playwright(position, max_results, headless)
                    all_jobs.extend(jobs)
                except Exception as e2:
                    logger.error(f"[Helmholtz] All methods failed: {e2}")
            await asyncio.sleep(1.5)

    logger.info(f"[Helmholtz] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _fetch_jobs(
    client: httpx.AsyncClient,
    position: str,
    max_results: int,
) -> List[JobSchema]:
    jobs = []

    # Try both the main Helmholtz board and FZJ (most relevant for energy/AI)
    for base_url in [HELMHOLTZ_JOBS, FZJ_JOBS]:
        params: dict = {"q": position}
        try:
            resp = await client.get(base_url, params=params)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # JSON-LD first
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            job = _parse_jsonld(item)
                            if job:
                                jobs.append(job)
                except Exception:
                    pass

            if not jobs:
                cards = (
                    soup.find_all("article", class_=lambda c: c and "job" in (c or "").lower())
                    or soup.find_all("div", class_=lambda c: c and any(
                        kw in (c or "").lower() for kw in ["job", "vacancy", "offer", "stelle"]
                    ))
                    or soup.find_all("tr", class_=lambda c: c and "job" in (c or "").lower())
                    or soup.find_all("li", class_=lambda c: c and "job" in (c or "").lower())
                )
                domain = base_url.split("/")[2]
                for card in cards[:max_results]:
                    job = _parse_card(card, f"https://{domain}")
                    if job:
                        jobs.append(job)
        except Exception:
            continue

        if len(jobs) >= max_results:
            break

    return jobs[:max_results]


def _parse_card(card, base_domain: str) -> Optional[JobSchema]:
    try:
        title_el = (
            card.find("h2") or card.find("h3") or card.find("h4")
            or card.find(class_=lambda c: c and "title" in (c or "").lower())
            or card.find("td", class_=lambda c: c and "title" in (c or "").lower())
        )
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        link_el = card.find("a", href=True)
        href = link_el["href"] if link_el else ""
        job_url = href if href.startswith("http") else urljoin(base_domain, href) if href else ""
        if not job_url:
            return None

        institute_el = card.find(class_=lambda c: c and any(
            kw in (c or "").lower() for kw in ["institute", "centre", "center", "employer", "facility"]
        ))
        company = institute_el.get_text(strip=True) if institute_el else "Helmholtz Association"

        location_el = card.find(class_=lambda c: c and ("location" in (c or "").lower() or "ort" in (c or "").lower()))
        location = location_el.get_text(strip=True) if location_el else "Deutschland"

        return JobSchema(
            source=JobSource.HELMHOLTZ,
            title=title,
            company=company,
            location=location,
            url=job_url,
        )
    except Exception as e:
        logger.debug(f"[Helmholtz] Card parse error: {e}")
        return None


def _parse_jsonld(data: dict) -> Optional[JobSchema]:
    try:
        title = data.get("title", "")
        if not title:
            return None
        url = data.get("url") or data.get("@id", "")
        org = data.get("hiringOrganization", {})
        company = org.get("name", "Helmholtz Association") if isinstance(org, dict) else "Helmholtz Association"
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
            source=JobSource.HELMHOLTZ,
            title=title,
            company=company,
            location=location or "Deutschland",
            url=url,
            date_posted=date_posted,
            description=(data.get("description") or "")[:2000] or None,
        )
    except Exception:
        return None


async def _scrape_playwright(
    position: str,
    max_results: int,
    headless: bool,
) -> List[JobSchema]:
    from playwright.async_api import async_playwright

    jobs = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = await browser.new_context(locale="en-GB")
        page = await context.new_page()

        url = f"{HELMHOLTZ_JOBS}?q={quote_plus(position)}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        for sel in ["button:has-text('Accept')", "button:has-text('I agree')",
                    "button:has-text('Akzeptieren')", "#onetrust-accept-btn-handler"]:
            try:
                btn = await page.wait_for_selector(sel, timeout=3000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await page.wait_for_timeout(2000)

        cards = await page.query_selector_all(
            "article, [class*='job'], [class*='vacancy'], [class*='offer'], li[class*='position']"
        )

        for card in cards[:max_results]:
            try:
                title_el = await card.query_selector("h2, h3, h4, [class*='title']")
                title = (await title_el.inner_text()).strip() if title_el else ""
                if not title:
                    continue

                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                job_url = href if (href or "").startswith("http") else urljoin(HELMHOLTZ_BASE, href) if href else ""
                if not job_url:
                    continue

                company_el = await card.query_selector("[class*='institute'], [class*='centre']")
                company = (await company_el.inner_text()).strip() if company_el else "Helmholtz Association"

                location_el = await card.query_selector("[class*='location']")
                loc = (await location_el.inner_text()).strip() if location_el else "Deutschland"

                jobs.append(JobSchema(
                    source=JobSource.HELMHOLTZ,
                    title=title,
                    company=company,
                    location=loc,
                    url=job_url,
                ))
            except Exception:
                continue

        await browser.close()

    return jobs

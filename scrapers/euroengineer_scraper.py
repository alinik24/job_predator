"""
EuroEngineerJobs scraper — European engineering job board with strong German presence.

EuroEngineerJobs (euroengineerjobs.com) specializes in electrical, mechanical,
software engineering positions across Europe. Also covers Experteer-style senior roles.

Method: HTTP + BeautifulSoup + JSON-LD.
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

EURO_BASE = "https://www.euroengineerjobs.com"
EURO_SEARCH = f"{EURO_BASE}/jobs"

# Also scrape Experteer (senior/executive roles, €40k+)
EXPERTEER_BASE = "https://www.experteer.de"
EXPERTEER_SEARCH = f"{EXPERTEER_BASE}/jobs/suche"


async def scrape_euroengineer(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """Scrape EuroEngineerJobs and Experteer.de for senior engineering roles."""
    if locations is None:
        locations = ["Germany"]

    all_jobs: List[JobSchema] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
        },
        follow_redirects=True,
        timeout=30,
    ) as client:
        for position in positions:
            for location in locations:
                logger.info(f"[EuroEngineer] Scraping '{position}' in '{location}'")

                # EuroEngineerJobs
                try:
                    jobs = await _fetch_euroengineer(client, position, location, max_results)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(f"[EuroEngineer] HTTP failed: {e}")

                # Experteer (German)
                try:
                    jobs = await _fetch_experteer(client, position, location, max_results // 2)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(f"[Experteer] HTTP failed: {e}")

                await asyncio.sleep(1)

    logger.info(f"[EuroEngineer+Experteer] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _fetch_euroengineer(
    client: httpx.AsyncClient,
    position: str,
    location: str,
    max_results: int,
) -> List[JobSchema]:
    jobs = []

    params = {
        "q": position,
        "location": location,
        "country": "de",
    }

    resp = await client.get(EURO_SEARCH, params=params)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "JobPosting" and len(jobs) < max_results:
                    job = _parse_jsonld(item, JobSource.EUROENGINEER)
                    if job:
                        jobs.append(job)
        except Exception:
            pass

    if not jobs:
        cards = (
            soup.find_all("article", class_=lambda c: c and "job" in (c or "").lower())
            or soup.find_all("div", class_=lambda c: c and "job" in (c or "").lower())
        )
        for card in cards[:max_results]:
            job = _parse_card(card, EURO_BASE, JobSource.EUROENGINEER)
            if job:
                jobs.append(job)

    return jobs


async def _fetch_experteer(
    client: httpx.AsyncClient,
    position: str,
    location: str,
    max_results: int,
) -> List[JobSchema]:
    jobs = []

    params = {
        "keyword": position,
        "location": location if location not in ("Germany", "Deutschland") else "Deutschland",
    }

    try:
        resp = await client.get(EXPERTEER_SEARCH, params=params)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "JobPosting" and len(jobs) < max_results:
                        job = _parse_jsonld(item, JobSource.EUROENGINEER)
                        if job:
                            job.source = JobSource.EUROENGINEER  # keep as EUROENGINEER since no separate enum
                            jobs.append(job)
            except Exception:
                pass

        if not jobs:
            cards = soup.find_all("article") or soup.find_all("div", class_=lambda c: c and "job" in (c or "").lower())
            for card in cards[:max_results]:
                job = _parse_card(card, EXPERTEER_BASE, JobSource.EUROENGINEER)
                if job:
                    jobs.append(job)

    except Exception as e:
        logger.debug(f"[Experteer] Fetch error: {e}")

    return jobs


def _parse_jsonld(data: dict, source: JobSource) -> Optional[JobSchema]:
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
            source=source,
            title=title,
            company=company,
            location=location,
            url=url,
            date_posted=date_posted,
        )
    except Exception:
        return None


def _parse_card(card, base_url: str, source: JobSource) -> Optional[JobSchema]:
    try:
        title_el = card.find("h2") or card.find("h3") or card.find("h4")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        link_el = card.find("a", href=True)
        href = link_el["href"] if link_el else ""
        job_url = href if href.startswith("http") else f"{base_url}{href}" if href else ""
        if not job_url:
            return None

        company_el = card.find(class_=lambda c: c and "company" in (c or "").lower())
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        location_el = card.find(class_=lambda c: c and "location" in (c or "").lower())
        location = location_el.get_text(strip=True) if location_el else ""

        return JobSchema(
            source=source,
            title=title,
            company=company,
            location=location,
            url=job_url,
        )
    except Exception as e:
        logger.debug(f"[EuroEngineer] Card parse error: {e}")
        return None

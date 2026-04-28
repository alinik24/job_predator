"""
Bundesagentur für Arbeit (BA) official REST API scraper.

The BA Jobsuche API covers the largest German-specific job database (>1M listings).
Auth: x-api-key header (public key used by the official BA Jobsuche webapp).

API base: https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional

import httpx
from loguru import logger

from core.models import JobSchema, JobSource

BA_BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"

# Public API key used by the official BA Jobsuche web app
BA_API_KEY = "jobboerse-jobsuche"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-DE",
    "x-api-key": BA_API_KEY,
    "Referer": "https://www.arbeitsagentur.de/",
}


async def _fetch_page(
    client: httpx.AsyncClient,
    keyword: str,
    location: str,
    page: int,
    page_size: int = 25,
) -> dict:
    params: dict = {
        "was": keyword,
        "page": page,
        "size": page_size,
        "angebotsart": 1,          # 1 = jobs (Arbeit)
        "veroeffentlichtseit": 7,  # published in last 7 days
    }
    # Empty wo = all of Germany; non-empty = city filter
    if location and location.lower() not in ("deutschland", "germany", ""):
        params["wo"] = location
        params["umkreis"] = 50  # 50km radius

    resp = await client.get(BA_BASE_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _parse_job(item: dict) -> Optional[JobSchema]:
    """Convert a BA API v6 job item to JobSchema."""
    try:
        ref_nr = item.get("referenznummer", "")
        extern_url = item.get("externeURL", "")
        job_url = (
            extern_url
            or (f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref_nr}" if ref_nr else "")
        )
        if not job_url:
            return None

        # Location from stellenlokationen
        location = "Deutschland"
        lokationen = item.get("stellenlokationen", [])
        if lokationen:
            adresse = lokationen[0].get("adresse", {})
            parts = list(filter(None, [
                adresse.get("ort"),
                adresse.get("plz"),
                adresse.get("region"),
            ]))
            if parts:
                location = ", ".join(parts)

        # Date
        date_posted = None
        date_str = item.get("datumErsteVeroeffentlichung")
        if date_str:
            try:
                date_posted = datetime.fromisoformat(date_str[:10])
            except Exception:
                pass

        # Salary
        salary_min = item.get("gehaltsspanneVon")
        salary_max = item.get("gehaltsspanneBis")

        return JobSchema(
            source=JobSource.ARBEITSAGENTUR,
            title=item.get("stellenangebotsTitel", "Unbekannte Stelle"),
            company=item.get("firma", "Unbekanntes Unternehmen"),
            location=location,
            is_remote=bool(item.get("homeofficemoeglich", False)),
            description=item.get("beschreibung", ""),
            url=job_url,
            apply_url=extern_url or job_url,
            salary_min=salary_min,
            salary_max=salary_max,
            easy_apply=False,
            date_posted=date_posted,
        )
    except Exception as e:
        logger.warning(f"[BA] Parse error: {e}")
        return None


async def scrape_bundesagentur(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    fetch_details: bool = False,
    headless: bool = True,
) -> List[JobSchema]:
    """
    Scrape jobs from Bundesagentur für Arbeit REST API (v6).

    Args:
        positions: Job title keywords (German or English)
        locations: German cities. None or ['Deutschland'] = all of Germany
        max_results: Max jobs per position+location combo
        fetch_details: Unused in v6 (details included in list response)
        headless: Unused, kept for API compatibility
    """
    if locations is None:
        locations = ["Deutschland"]

    all_jobs: List[JobSchema] = []

    async with httpx.AsyncClient(verify=False) as client:
        for position in positions:
            for location in locations:
                logger.info(f"[BA] Scraping '{position}' in '{location}'")
                collected = 0
                page = 1
                page_size = min(25, max_results)

                while collected < max_results:
                    try:
                        data = await _fetch_page(client, position, location, page, page_size)
                        items = data.get("ergebnisliste", []) or []

                        if not items:
                            break

                        for item in items:
                            if collected >= max_results:
                                break
                            job = _parse_job(item)
                            if job:
                                all_jobs.append(job)
                                collected += 1

                        total = data.get("maxErgebnisse", 0)
                        logger.debug(
                            f"[BA] Page {page} — {len(items)} items, total available: {total}"
                        )

                        if collected >= total or len(items) < page_size:
                            break
                        page += 1

                    except httpx.HTTPStatusError as e:
                        logger.error(f"[BA] HTTP {e.response.status_code}: {e}")
                        break
                    except Exception as e:
                        logger.error(f"[BA] Error: {e}")
                        break

                    await asyncio.sleep(0.5)

    logger.info(f"[BA] Total collected: {len(all_jobs)} jobs")
    return all_jobs

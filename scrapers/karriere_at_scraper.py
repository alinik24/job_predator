"""
Karriere.at scraper — Austria's largest job portal, covers many German-language
positions that are also relevant for Germany (Munich, Bavaria, border regions).

Has an undocumented JSON search API endpoint.
Method: JSON API + HTTP.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from core.models import JobSchema, JobSource

KARRIERE_BASE = "https://www.karriere.at"
KARRIERE_SEARCH = f"{KARRIERE_BASE}/jobs"
KARRIERE_API = f"{KARRIERE_BASE}/api/v1/jobs"


async def scrape_karriere_at(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """Scrape karriere.at for Austrian/German-language tech positions."""
    if locations is None:
        locations = [""]  # empty = all Austria

    all_jobs: List[JobSchema] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-AT,de;q=0.9",
            "Accept": "application/json, text/html, */*",
        },
        follow_redirects=True,
        timeout=30,
    ) as client:
        for position in positions:
            for location in locations:
                logger.info(f"[Karriere.at] Scraping '{position}' in '{location or 'AT'}'")
                try:
                    jobs = await _fetch_via_api(client, position, location, max_results)
                    if not jobs:
                        jobs = await _fetch_via_html(client, position, location, max_results)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.error(f"[Karriere.at] Failed: {e}")
                await asyncio.sleep(1)

    logger.info(f"[Karriere.at] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _fetch_via_api(
    client: httpx.AsyncClient,
    position: str,
    location: str,
    max_results: int,
) -> List[JobSchema]:
    """Try the internal JSON API."""
    jobs = []
    page = 1
    per_page = min(20, max_results)

    while len(jobs) < max_results:
        params: dict = {
            "keyword": position,
            "page": page,
            "perPage": per_page,
        }
        if location:
            params["location"] = location

        try:
            resp = await client.get(
                KARRIERE_API,
                params=params,
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200 or "application/json" not in resp.headers.get("content-type", ""):
                return jobs

            data = resp.json()
            items = data.get("jobs") or data.get("data") or data.get("results") or []
            if not items:
                break

            for item in items:
                if len(jobs) >= max_results:
                    break
                job = _parse_api_item(item)
                if job:
                    jobs.append(job)

            if len(items) < per_page:
                break
            page += 1

        except Exception as e:
            logger.debug(f"[Karriere.at] API error: {e}")
            break

    return jobs


async def _fetch_via_html(
    client: httpx.AsyncClient,
    position: str,
    location: str,
    max_results: int,
) -> List[JobSchema]:
    jobs = []
    page = 1

    while len(jobs) < max_results:
        url = f"{KARRIERE_SEARCH}/{quote_plus(position)}"
        params: dict = {"page": page}
        if location:
            params["location"] = location

        resp = await client.get(url, params=params)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        cards = (
            soup.find_all("article", class_=lambda c: c and "job" in (c or "").lower())
            or soup.find_all("div", class_=lambda c: c and "m-jobsListItem" in (c or ""))
            or soup.find_all("li", class_=lambda c: c and "job" in (c or "").lower())
        )
        if not cards:
            break

        for card in cards:
            if len(jobs) >= max_results:
                break
            job = _parse_html_card(card)
            if job:
                jobs.append(job)

        next_link = soup.find("a", attrs={"rel": "next"})
        if not next_link:
            break
        page += 1

    return jobs


def _parse_api_item(item: dict) -> Optional[JobSchema]:
    try:
        title = item.get("title") or item.get("name", "")
        if not title:
            return None
        url = item.get("url") or item.get("link", "")
        if not url:
            slug = item.get("slug", "")
            url = f"{KARRIERE_BASE}/jobs/{slug}" if slug else ""
        company = ""
        comp = item.get("company") or item.get("employer") or {}
        if isinstance(comp, dict):
            company = comp.get("name", "Unknown")
        elif isinstance(comp, str):
            company = comp
        location = item.get("location") or item.get("city") or ""
        if isinstance(location, dict):
            location = location.get("name", "")

        date_posted = None
        dp = item.get("publishedAt") or item.get("datePosted")
        if dp:
            try:
                date_posted = datetime.fromisoformat(str(dp)[:10])
            except Exception:
                pass

        return JobSchema(
            source=JobSource.KARRIERE_AT,
            title=title,
            company=company,
            location=location,
            url=url,
            date_posted=date_posted,
        )
    except Exception:
        return None


def _parse_html_card(card) -> Optional[JobSchema]:
    try:
        title_el = card.find("h2") or card.find("h3") or card.find("a", class_=lambda c: c and "title" in (c or "").lower())
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        link_el = card.find("a", href=True)
        href = link_el["href"] if link_el else ""
        job_url = href if href.startswith("http") else f"{KARRIERE_BASE}{href}" if href else ""
        if not job_url:
            return None

        company_el = card.find(class_=lambda c: c and "company" in (c or "").lower())
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        location_el = card.find(class_=lambda c: c and "location" in (c or "").lower())
        location = location_el.get_text(strip=True) if location_el else ""

        return JobSchema(
            source=JobSource.KARRIERE_AT,
            title=title,
            company=company,
            location=location,
            url=job_url,
        )
    except Exception as e:
        logger.debug(f"[Karriere.at] HTML card parse error: {e}")
        return None

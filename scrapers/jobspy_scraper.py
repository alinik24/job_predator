"""
JobSpy scraper — LinkedIn, Indeed DE, Glassdoor in one unified call.

JobSpy returns a pandas DataFrame; we convert to our JobSchema list.
Docs: https://github.com/cullenwatson/JobSpy
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional

from loguru import logger

from core.config import settings
from core.models import JobSchema, JobSource


def _map_source(site: str) -> str:
    mapping = {
        "linkedin": JobSource.LINKEDIN,
        "indeed": JobSource.INDEED,
        "glassdoor": JobSource.GLASSDOOR,
        "zip_recruiter": JobSource.OTHER,
    }
    return mapping.get(site.lower(), JobSource.OTHER)


def scrape_jobspy(
    positions: List[str],
    locations: Optional[List[str]] = None,
    hours_old: int = 72,
    results_wanted: int = 50,
    proxy: Optional[str] = None,
) -> List[JobSchema]:
    """
    Synchronous JobSpy scrape. Call from asyncio via run_in_executor.
    Returns a list of JobSchema objects.
    """
    try:
        from jobspy import scrape_jobs  # type: ignore
    except ImportError:
        logger.error("python-jobspy not installed. Run: pip install python-jobspy")
        return []

    if locations is None:
        locations = ["Germany"]

    all_jobs: List[JobSchema] = []

    for position in positions:
        for location in locations:
            logger.info(f"[JobSpy] Scraping '{position}' in '{location}'")
            try:
                proxies = {"http": proxy, "https": proxy} if proxy else None
                df = scrape_jobs(
                    site_name=["linkedin", "indeed", "glassdoor"],
                    search_term=position,
                    location=location,
                    results_wanted=results_wanted,
                    hours_old=hours_old,
                    country_indeed="germany",
                    description_format="markdown",
                    proxies=proxies,
                    verbose=False,
                )

                if df is None or df.empty:
                    logger.warning(f"[JobSpy] No results for '{position}' @ '{location}'")
                    continue

                for _, row in df.iterrows():
                    try:
                        job = JobSchema(
                            source=_map_source(str(row.get("site", "other"))),
                            title=str(row.get("title", "Unknown")),
                            company=str(row.get("company", "Unknown")),
                            location=str(row.get("location", "")),
                            is_remote=bool(row.get("is_remote", False)),
                            salary_min=_safe_float(row.get("min_amount")),
                            salary_max=_safe_float(row.get("max_amount")),
                            description=str(row.get("description", "")),
                            url=str(row.get("job_url", "")),
                            apply_url=str(row.get("job_url_direct", "")) or None,
                            easy_apply=bool(row.get("is_easy_apply", False)),
                            date_posted=_safe_date(row.get("date_posted")),
                        )
                        if job.url:
                            all_jobs.append(job)
                    except Exception as e:
                        logger.warning(f"[JobSpy] Row parse error: {e}")

            except Exception as e:
                logger.error(f"[JobSpy] Scrape failed for '{position}' @ '{location}': {e}")

    logger.info(f"[JobSpy] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def scrape_jobspy_async(
    positions: List[str],
    locations: Optional[List[str]] = None,
    hours_old: int = 72,
    results_wanted: int = 50,
) -> List[JobSchema]:
    """Async wrapper — runs blocking JobSpy in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: scrape_jobspy(
            positions=positions,
            locations=locations,
            hours_old=hours_old,
            results_wanted=results_wanted,
            proxy=settings.scrape_proxy,
        ),
    )


def _safe_float(val) -> Optional[float]:
    try:
        if val is None or str(val).lower() in ("nan", "none", ""):
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_date(val) -> Optional[datetime]:
    if val is None:
        return None
    try:
        if isinstance(val, datetime):
            return val
        return datetime.fromisoformat(str(val))
    except Exception:
        return None

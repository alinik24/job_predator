"""
Wellfound (formerly AngelList Talent) scraper — startup jobs worldwide.

wellfound.com hosts 130 000+ startup jobs globally including Germany.
It shows salary ranges and equity upfront — great for transparency.
Strong EU/Berlin startup coverage (N26, Klarna, Personio, etc.).

Method: Playwright (React SPA) with XHR interception.
"""
from __future__ import annotations

import asyncio
import json
from typing import List, Optional
from urllib.parse import quote_plus

from loguru import logger

from core.models import JobSchema, JobSource

WELLFOUND_BASE = "https://wellfound.com"
WELLFOUND_SEARCH = f"{WELLFOUND_BASE}/jobs"


async def scrape_wellfound(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """Scrape Wellfound for startup job listings."""
    all_jobs: List[JobSchema] = []
    locs = locations or ["Germany"]

    for position in positions:
        for location in locs:
            logger.info(f"[Wellfound] Scraping '{position}' in '{location}'")
            try:
                jobs = await _scrape_playwright(position, location, max_results, headless)
                all_jobs.extend(jobs)
            except Exception as e:
                logger.error(f"[Wellfound] Error: {e}")
            await asyncio.sleep(2)

    logger.info(f"[Wellfound] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _scrape_playwright(
    position: str,
    location: str,
    max_results: int,
    headless: bool,
) -> List[JobSchema]:
    from playwright.async_api import async_playwright

    jobs: List[JobSchema] = []
    api_jobs: List[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # Intercept GraphQL/REST API responses that carry job data
        async def on_response(response):
            url = response.url
            if any(kw in url for kw in ["/api/", "/graphql", "jobs", "search"]):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = await response.json()
                        _extract_api_jobs(body, api_jobs)
                except Exception:
                    pass

        page.on("response", on_response)

        search_url = (
            f"{WELLFOUND_SEARCH}?q={quote_plus(position)}"
            f"&l={quote_plus(location)}"
        )
        await page.goto(search_url, wait_until="networkidle", timeout=45000)

        # Accept cookies if present
        for sel in ["button:has-text('Accept')", "button:has-text('I agree')",
                    "button[data-testid*='accept']"]:
            try:
                btn = await page.wait_for_selector(sel, timeout=3000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await page.wait_for_timeout(3000)

        # If API interception gave us jobs, use those
        if api_jobs:
            for jd in api_jobs[:max_results]:
                job = _parse_api_job(jd)
                if job:
                    jobs.append(job)
        else:
            # HTML fallback
            job_cards = await page.query_selector_all(
                "[class*='job-listing'], [class*='JobListingItem'], [data-test*='job'], "
                "div[class*='styles_component']"
            )
            for card in job_cards[:max_results]:
                try:
                    title_el = await card.query_selector(
                        "h2, h3, [class*='title'], [class*='name'], [class*='role']"
                    )
                    title = (await title_el.inner_text()).strip() if title_el else ""
                    if not title:
                        continue

                    link_el = await card.query_selector("a[href*='/jobs/']")
                    href = await link_el.get_attribute("href") if link_el else ""
                    job_url = href if (href or "").startswith("http") else f"{WELLFOUND_BASE}{href}" if href else ""
                    if not job_url:
                        continue

                    company_el = await card.query_selector(
                        "[class*='company'], [class*='startup'], [class*='employer']"
                    )
                    company = (await company_el.inner_text()).strip() if company_el else "Startup"

                    loc_el = await card.query_selector("[class*='location']")
                    loc = (await loc_el.inner_text()).strip() if loc_el else location

                    salary_el = await card.query_selector("[class*='salary'], [class*='compensation']")
                    salary_text = (await salary_el.inner_text()).strip() if salary_el else ""

                    salary_min, salary_max = _parse_salary(salary_text)

                    jobs.append(JobSchema(
                        source=JobSource.WELLFOUND,
                        title=title,
                        company=company,
                        location=loc,
                        url=job_url,
                        salary_min=salary_min,
                        salary_max=salary_max,
                    ))
                except Exception:
                    continue

        await browser.close()

    return jobs


def _extract_api_jobs(body: dict, collector: list) -> None:
    """Recursively extract job objects from API response."""
    if isinstance(body, list):
        for item in body:
            if isinstance(item, dict) and any(k in item for k in ["title", "role", "jobTitle"]):
                collector.append(item)
            else:
                _extract_api_jobs(item, collector)
    elif isinstance(body, dict):
        # Check if this is a job-like dict
        if any(k in body for k in ["title", "role", "jobTitle"]):
            collector.append(body)
        for v in body.values():
            if isinstance(v, (dict, list)):
                _extract_api_jobs(v, collector)


def _parse_api_job(data: dict) -> Optional[JobSchema]:
    try:
        title = (
            data.get("title") or data.get("role") or data.get("jobTitle") or ""
        ).strip()
        if not title:
            return None

        url = data.get("url") or data.get("applicationUrl") or data.get("jobUrl") or ""
        if not url:
            return None
        if not url.startswith("http"):
            url = f"{WELLFOUND_BASE}{url}"

        company_data = data.get("company") or data.get("startup") or {}
        company = (
            company_data.get("name") if isinstance(company_data, dict) else str(company_data)
        ) or "Startup"

        location_data = data.get("location") or data.get("locationName") or ""
        location = location_data if isinstance(location_data, str) else (
            location_data.get("city") or location_data.get("name", "Germany")
            if isinstance(location_data, dict) else "Germany"
        )

        salary_min = data.get("salaryMin") or data.get("compensationMin")
        salary_max = data.get("salaryMax") or data.get("compensationMax")
        is_remote = data.get("remote", False) or "remote" in str(location).lower()

        return JobSchema(
            source=JobSource.WELLFOUND,
            title=title,
            company=company,
            location=location,
            url=url,
            salary_min=float(salary_min) if salary_min else None,
            salary_max=float(salary_max) if salary_max else None,
            is_remote=is_remote,
            description=data.get("description", "")[:2000] if data.get("description") else None,
        )
    except Exception:
        return None


def _parse_salary(text: str):
    """Parse '€60k - €90k' or '$60,000 - $90,000' into (min, max) floats."""
    import re
    if not text:
        return None, None
    nums = re.findall(r"[\d,]+(?:k)?", text.lower().replace(",", ""))
    values = []
    for n in nums:
        try:
            val = float(n.replace("k", "")) * (1000 if "k" in n else 1)
            values.append(val)
        except ValueError:
            pass
    if len(values) >= 2:
        return min(values), max(values)
    if len(values) == 1:
        return values[0], None
    return None, None

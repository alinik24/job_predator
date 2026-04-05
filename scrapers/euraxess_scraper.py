"""
EURAXESS scraper — pan-European research job portal.

EURAXESS (euraxess.ec.europa.eu) is the European Commission's portal for
researcher mobility, covering PhD positions, postdocs, research engineer
and research scientist roles across 43 European countries.

Extremely relevant for candidates with academic/research backgrounds.

Method: HTTP REST API (public, no auth) + HTML fallback.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote_plus

import httpx
from loguru import logger

from core.models import JobSchema, JobSource

EURAXESS_BASE = "https://euraxess.ec.europa.eu"
EURAXESS_SEARCH = f"{EURAXESS_BASE}/jobs/search"


async def scrape_euraxess(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
    country_code: str = "DE",
) -> List[JobSchema]:
    """Scrape EURAXESS for research positions (primarily Germany)."""
    all_jobs: List[JobSchema] = []

    async with httpx.AsyncClient(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "en-GB,en;q=0.9,de;q=0.8",
        },
        follow_redirects=True,
        timeout=30,
    ) as client:
        for position in positions:
            logger.info(f"[EURAXESS] Scraping '{position}' in '{country_code}'")
            try:
                jobs = await _fetch_jobs(client, position, country_code, max_results)
                all_jobs.extend(jobs)
            except Exception as e:
                logger.warning(f"[EURAXESS] HTTP failed ({e}), trying Playwright...")
                try:
                    jobs = await _scrape_playwright(position, country_code, max_results, headless)
                    all_jobs.extend(jobs)
                except Exception as e2:
                    logger.error(f"[EURAXESS] All methods failed: {e2}")
            await asyncio.sleep(1.5)

    logger.info(f"[EURAXESS] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _fetch_jobs(
    client: httpx.AsyncClient,
    position: str,
    country_code: str,
    max_results: int,
) -> List[JobSchema]:
    jobs = []
    page = 0
    per_page = min(25, max_results)

    while len(jobs) < max_results:
        params = {
            "query": position,
            "country": country_code,
            "page": page,
            "per_page": per_page,
        }
        resp = await client.get(EURAXESS_SEARCH, params=params)
        resp.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")

        # EURAXESS uses article tags with class 'job-result' or similar
        cards = (
            soup.find_all("article", class_=lambda c: c and "job" in (c or "").lower())
            or soup.find_all("div", class_=lambda c: c and ("result" in (c or "").lower() or "job" in (c or "").lower()))
            or soup.find_all("li", class_=lambda c: c and "job" in (c or "").lower())
        )

        if not cards:
            # Try JSON-LD
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    import json
                    data = json.loads(script.string or "")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") == "JobPosting":
                            job = _parse_jsonld(item)
                            if job:
                                jobs.append(job)
                except Exception:
                    pass
            break

        for card in cards:
            if len(jobs) >= max_results:
                break
            job = _parse_card(card)
            if job:
                jobs.append(job)

        # Check pagination
        next_page = soup.find("a", attrs={"rel": "next"})
        if not next_page or len(cards) == 0:
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
        job_url = href if href.startswith("http") else f"{EURAXESS_BASE}{href}" if href else ""
        if not job_url:
            return None

        # Institution / company
        institution_el = card.find(class_=lambda c: c and any(
            kw in (c or "").lower() for kw in ["institution", "organisation", "employer", "company"]
        ))
        company = institution_el.get_text(strip=True) if institution_el else "Research Institute"

        # Location
        location_el = card.find(class_=lambda c: c and "location" in (c or "").lower())
        location = location_el.get_text(strip=True) if location_el else "Germany"

        # Deadline / date
        date_el = card.find(class_=lambda c: c and any(
            kw in (c or "").lower() for kw in ["date", "deadline", "posted"]
        ))
        date_text = date_el.get_text(strip=True) if date_el else ""
        date_posted = None
        if date_text:
            for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"]:
                try:
                    date_posted = datetime.strptime(date_text[:10], fmt)
                    break
                except ValueError:
                    continue

        return JobSchema(
            source=JobSource.EURAXESS,
            title=title,
            company=company,
            location=location,
            url=job_url,
            date_posted=date_posted,
        )
    except Exception as e:
        logger.debug(f"[EURAXESS] Card parse error: {e}")
        return None


def _parse_jsonld(data: dict) -> Optional[JobSchema]:
    try:
        title = data.get("title", "")
        if not title:
            return None
        url = data.get("url") or data.get("@id", "")
        org = data.get("hiringOrganization", {})
        company = org.get("name", "Research Institute") if isinstance(org, dict) else "Research Institute"
        loc = data.get("jobLocation", {})
        location = ""
        if isinstance(loc, dict):
            addr = loc.get("address", {})
            if isinstance(addr, dict):
                location = addr.get("addressLocality") or addr.get("addressCountry", "")
        date_posted = None
        dp = data.get("datePosted", "")
        if dp:
            try:
                date_posted = datetime.fromisoformat(dp[:10])
            except ValueError:
                pass
        return JobSchema(
            source=JobSource.EURAXESS,
            title=title,
            company=company,
            location=location or "Europe",
            url=url,
            date_posted=date_posted,
            description=data.get("description", "")[:2000] if data.get("description") else None,
        )
    except Exception:
        return None


async def _scrape_playwright(
    position: str,
    country_code: str,
    max_results: int,
    headless: bool,
) -> List[JobSchema]:
    from playwright.async_api import async_playwright

    jobs = []
    url = f"{EURAXESS_SEARCH}?query={quote_plus(position)}&country={country_code}"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = await browser.new_context(locale="en-GB")
        page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Accept cookies
        for sel in ["button:has-text('Accept')", "button:has-text('I agree')",
                    "#cookie-accept", "button[id*='accept']"]:
            try:
                btn = await page.wait_for_selector(sel, timeout=3000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await page.wait_for_timeout(2000)

        cards = await page.query_selector_all(
            "article, [class*='job-result'], [class*='job-item'], li[class*='job']"
        )

        for card in cards[:max_results]:
            try:
                title_el = await card.query_selector("h2, h3, h4, [class*='title']")
                title = (await title_el.inner_text()).strip() if title_el else ""
                if not title:
                    continue

                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                job_url = href if (href or "").startswith("http") else f"{EURAXESS_BASE}{href}" if href else ""
                if not job_url:
                    continue

                company_el = await card.query_selector(
                    "[class*='institution'], [class*='organisation'], [class*='company']"
                )
                company = (await company_el.inner_text()).strip() if company_el else "Research Institute"

                location_el = await card.query_selector("[class*='location'], [class*='country']")
                loc = (await location_el.inner_text()).strip() if location_el else "Germany"

                jobs.append(JobSchema(
                    source=JobSource.EURAXESS,
                    title=title,
                    company=company,
                    location=loc,
                    url=job_url,
                ))
            except Exception:
                continue

        await browser.close()

    return jobs

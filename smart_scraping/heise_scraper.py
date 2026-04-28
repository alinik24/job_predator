"""
Heise Jobs scraper — German tech/IT job board by Heise Medien.

heise jobs is the go-to board for software developers, IT professionals
in German-speaking countries. Covers jobs.heise.de.

Method: HTTP + BeautifulSoup (site renders mostly server-side).
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

HEISE_BASE = "https://jobs.heise.de"
HEISE_SEARCH = f"{HEISE_BASE}/search"


async def scrape_heise(
    positions: List[str],
    locations: Optional[List[str]] = None,
    max_results: int = 50,
    headless: bool = True,
) -> List[JobSchema]:
    """
    Scrape Heise Jobs via HTTP + BeautifulSoup.
    Falls back to Playwright if JS-rendered content is detected.
    """
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
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
        follow_redirects=True,
        timeout=30,
    ) as client:
        for position in positions:
            for location in locations:
                logger.info(f"[Heise] Scraping '{position}' in '{location or 'DE'}'")
                try:
                    jobs = await _fetch_heise_jobs(client, position, location, max_results)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(f"[Heise] HTTP failed ({e}), trying Playwright...")
                    try:
                        jobs = await _scrape_playwright(position, location, max_results, headless)
                        all_jobs.extend(jobs)
                    except Exception as e2:
                        logger.error(f"[Heise] Both methods failed: {e2}")

                await asyncio.sleep(1)

    logger.info(f"[Heise] Total collected: {len(all_jobs)} jobs")
    return all_jobs


async def _fetch_heise_jobs(
    client: httpx.AsyncClient,
    position: str,
    location: str,
    max_results: int,
) -> List[JobSchema]:
    jobs = []
    page = 1

    while len(jobs) < max_results:
        params = {"q": position, "page": page}
        if location:
            params["location"] = location

        resp = await client.get(HEISE_SEARCH, params=params)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Heise Jobs uses article or li elements for job cards
        cards = (
            soup.find_all("article", class_=lambda c: c and "job" in (c or "").lower())
            or soup.find_all("li", class_=lambda c: c and "job" in (c or "").lower())
            or soup.find_all("div", class_=lambda c: c and "job-item" in (c or "").lower())
        )

        if not cards:
            # Check for JSON-LD structured data
            scripts = soup.find_all("script", type="application/ld+json")
            for script in scripts:
                try:
                    import json
                    data = json.loads(script.string or "")
                    if isinstance(data, list):
                        for item in data:
                            if item.get("@type") == "JobPosting":
                                job = _parse_jsonld(item)
                                if job:
                                    jobs.append(job)
                    elif data.get("@type") == "JobPosting":
                        job = _parse_jsonld(data)
                        if job:
                            jobs.append(job)
                except Exception:
                    pass
            if not jobs:
                break
            break

        for card in cards:
            if len(jobs) >= max_results:
                break
            job = _parse_card(card)
            if job:
                jobs.append(job)

        next_link = soup.find("a", attrs={"rel": "next"}) or soup.find(
            "a", string=lambda s: s and ("weiter" in (s or "").lower() or "next" in (s or "").lower())
        )
        if not next_link:
            break
        page += 1

    return jobs


def _parse_card(card) -> Optional[JobSchema]:
    try:
        title_el = (
            card.find("h2") or card.find("h3") or card.find("h1")
            or card.find(class_=lambda c: c and "title" in (c or "").lower())
        )
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        link_el = card.find("a", href=True)
        href = link_el["href"] if link_el else ""
        job_url = href if href.startswith("http") else f"{HEISE_BASE}{href}" if href else ""
        if not job_url:
            return None

        company_el = card.find(class_=lambda c: c and ("company" in (c or "").lower() or "arbeit" in (c or "").lower()))
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        location_el = card.find(class_=lambda c: c and ("location" in (c or "").lower() or "ort" in (c or "").lower()))
        location = location_el.get_text(strip=True) if location_el else ""

        card_text = card.get_text().lower()
        is_remote = any(kw in card_text for kw in ["remote", "homeoffice", "home office"])

        return JobSchema(
            source=JobSource.HEISE,
            title=title,
            company=company,
            location=location,
            is_remote=is_remote,
            url=job_url,
        )
    except Exception as e:
        logger.debug(f"[Heise] Card parse error: {e}")
        return None


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
        return JobSchema(
            source=JobSource.HEISE,
            title=title,
            company=company,
            location=location,
            url=url,
        )
    except Exception:
        return None


async def _scrape_playwright(
    position: str,
    location: str,
    max_results: int,
    headless: bool,
) -> List[JobSchema]:
    import json as _json
    from playwright.async_api import async_playwright

    jobs = []
    captured_responses: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=["--no-sandbox"])
        context = await browser.new_context(locale="de-DE")
        page = await context.new_page()

        # Intercept any XHR/fetch that returns job data
        async def on_response(response):
            url = response.url
            if any(kw in url for kw in ["jobs", "search", "jobposting", "offers", "stellenangebot"]):
                try:
                    body = await response.body()
                    data = _json.loads(body)
                    captured_responses.append({"url": url, "data": data})
                except Exception:
                    pass

        page.on("response", on_response)

        params = f"?q={quote_plus(position)}"
        if location:
            params += f"&location={quote_plus(location)}"
        await page.goto(f"{HEISE_SEARCH}{params}", wait_until="networkidle", timeout=45000)

        # Cookie banner
        for sel in ["button:has-text('Alle akzeptieren')", "button:has-text('Akzeptieren')", "[id*='accept']"]:
            try:
                btn = await page.wait_for_selector(sel, timeout=2000)
                if btn:
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                continue

        await page.wait_for_timeout(3000)

        # Try to parse any captured API responses
        for resp in captured_responses:
            data = resp["data"]
            items = (
                data.get("jobs") or data.get("results") or data.get("items")
                or data.get("stellenangebote") or []
            )
            if isinstance(items, list):
                for item in items[:max_results]:
                    if isinstance(item, dict):
                        title = item.get("title") or item.get("name") or item.get("stellenangebotsTitel", "")
                        url_val = item.get("url") or item.get("jobUrl") or item.get("applyUrl", "")
                        company = (
                            item.get("company") or item.get("employer") or
                            (item.get("hiringOrganization") or {}).get("name", "Unknown")
                            if isinstance(item.get("hiringOrganization"), dict) else "Unknown"
                        )
                        if title and url_val:
                            jobs.append(JobSchema(
                                source=JobSource.HEISE,
                                title=title,
                                company=company,
                                url=url_val if url_val.startswith("http") else f"{HEISE_BASE}{url_val}",
                            ))

        # Fallback: scrape rendered HTML job cards
        if not jobs:
            # jobs.heise.de uses data-job-id attributes or similar
            cards = await page.query_selector_all(
                "a[href*='/job/'], a[href*='/stelle/'], [data-job-id], [data-testid*='job']"
            )
            seen_urls = set()
            for card in cards[:max_results]:
                try:
                    href = await card.get_attribute("href") or ""
                    job_url = href if href.startswith("http") else f"{HEISE_BASE}{href}" if href else ""
                    if not job_url or job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    title_el = await card.query_selector("h2, h3, h4, [class*='title'], [class*='Title']")
                    title = (await title_el.inner_text()).strip() if title_el else (await card.inner_text()).strip()[:80]
                    if not title or len(title) < 3:
                        continue

                    company_el = await card.query_selector("[class*='company'], [class*='Company'], [class*='employer']")
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"

                    jobs.append(JobSchema(
                        source=JobSource.HEISE,
                        title=title,
                        company=company,
                        url=job_url,
                    ))
                except Exception:
                    continue

        await browser.close()

    return jobs

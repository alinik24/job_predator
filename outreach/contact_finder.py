"""
HR Contact Finder — locates recruiter/HR contacts for companies.

Sources (in priority order):
  1. Hunter.io API — most reliable email finder, great for German companies
  2. LinkedIn people search via Playwright — find HR/recruiter profiles
  3. Company website pattern guessing (firstname.lastname@company.com)

Stores found contacts in the hr_contacts table.
"""
from __future__ import annotations

import asyncio
import re
from typing import List, Optional

import httpx
from loguru import logger

from core.config import settings
from core.database import get_session
from core.models import HRContact, Job

HUNTER_BASE = "https://api.hunter.io/v2"

HR_TITLES = [
    "HR", "Recruiter", "Talent", "Human Resources", "People",
    "Personalreferent", "Recruiting", "Talent Acquisition",
    "Head of HR", "HR Manager", "HR Business Partner",
]


class ContactFinder:
    """Finds HR contacts for companies posting jobs."""

    def __init__(self):
        self.hunter_key = settings.hunter_api_key

    async def find_for_job(self, job: Job) -> List[HRContact]:
        """
        Find HR contacts for the company posting this job.
        Returns list of newly stored HRContact objects.
        """
        logger.info(f"[ContactFinder] Finding HR contacts for: {job.company}")
        contacts = []

        # Try Hunter.io first
        if self.hunter_key:
            domain = self._extract_domain(job)
            if domain:
                hunter_contacts = await self._search_hunter(domain, job.id)
                contacts.extend(hunter_contacts)

        # If no contacts found, try LinkedIn
        if not contacts:
            linkedin_contacts = await self._search_linkedin(job.company, job.id)
            contacts.extend(linkedin_contacts)

        logger.info(f"[ContactFinder] Found {len(contacts)} contacts for {job.company}")
        return contacts

    async def _search_hunter(self, domain: str, job_id) -> List[HRContact]:
        """Search Hunter.io for HR contacts at a domain."""
        try:
            async with httpx.AsyncClient() as client:
                # Domain search — get all emails for the company
                response = await client.get(
                    f"{HUNTER_BASE}/domain-search",
                    params={
                        "domain": domain,
                        "api_key": self.hunter_key,
                        "limit": 10,
                        "type": "personal",
                    },
                    timeout=15,
                )
                response.raise_for_status()
                data = response.json()

            emails = data.get("data", {}).get("emails", [])
            if not emails:
                logger.debug(f"[Hunter] No emails found for domain: {domain}")
                return []

            contacts = []
            for email_data in emails:
                # Filter for HR-related roles
                position = email_data.get("position", "") or ""
                department = email_data.get("department", "") or ""

                is_hr = any(
                    kw.lower() in position.lower() or kw.lower() in department.lower()
                    for kw in HR_TITLES
                )

                # Still include even if not explicitly HR (recruiter might not have title)
                first = email_data.get("first_name", "")
                last = email_data.get("last_name", "")
                full_name = f"{first} {last}".strip() or None
                email = email_data.get("value")
                confidence = email_data.get("confidence", 0)

                if not email:
                    continue

                contact = await self._store_contact(
                    job_id=job_id,
                    company=domain,
                    full_name=full_name,
                    title=position,
                    email=email,
                    confidence_score=confidence / 100.0,
                    source="hunter.io",
                    is_hr=is_hr,
                )
                contacts.append(contact)

            # Also try email finder for specific HR names
            if not any(c for c in contacts if _is_hr_title(c.title or "")):
                hr_contacts = await self._hunter_find_hr(domain, job_id)
                contacts.extend(hr_contacts)

            return contacts

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("[Hunter] Rate limit hit")
            else:
                logger.error(f"[Hunter] HTTP error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"[Hunter] Error searching {domain}: {e}")
            return []

    async def _hunter_find_hr(self, domain: str, job_id) -> List[HRContact]:
        """Use Hunter.io email finder to look for specific HR roles."""
        hr_role_queries = ["hr", "recruiting", "talent", "personalreferent"]
        found = []

        async with httpx.AsyncClient() as client:
            for role in hr_role_queries:
                try:
                    response = await client.get(
                        f"{HUNTER_BASE}/email-finder",
                        params={
                            "domain": domain,
                            "api_key": self.hunter_key,
                            "role": role,
                        },
                        timeout=10,
                    )
                    if response.status_code == 200:
                        data = response.json().get("data", {})
                        email = data.get("email")
                        if email and data.get("score", 0) > 50:
                            contact = await self._store_contact(
                                job_id=job_id,
                                company=domain,
                                full_name=f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
                                title=data.get("position"),
                                email=email,
                                confidence_score=data.get("score", 0) / 100.0,
                                source="hunter.io",
                                is_hr=True,
                            )
                            found.append(contact)
                    await asyncio.sleep(0.5)
                except Exception:
                    continue

        return found

    async def _search_linkedin(self, company: str, job_id) -> List[HRContact]:
        """
        Search LinkedIn for HR contacts at the company using Playwright.
        This is a best-effort search — results depend on LinkedIn's search visibility.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return []

        if not settings.linkedin_email:
            logger.debug("[LinkedIn] No credentials — skipping contact search")
            return []

        contacts = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                # Login
                await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
                await page.fill("#username", settings.linkedin_email)
                await page.fill("#password", settings.linkedin_password or "")
                await page.click("button[type='submit']")
                await page.wait_for_timeout(3000)

                if "feed" not in page.url and "jobs" not in page.url:
                    return []

                # Search for HR people at this company
                search_query = f'"{company}" (recruiter OR "HR" OR "talent acquisition")'
                search_url = (
                    "https://www.linkedin.com/search/results/people/"
                    f"?keywords={search_query.replace(' ', '%20')}&origin=GLOBAL_SEARCH_HEADER"
                )
                await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)

                # Extract people from results
                cards = await page.query_selector_all(
                    ".entity-result__item, [data-chameleon-result-urn]"
                )

                for card in cards[:5]:  # Limit to top 5 results
                    try:
                        name_el = await card.query_selector(
                            ".entity-result__title-text a, span.actor-name"
                        )
                        name = (await name_el.inner_text()).strip() if name_el else ""

                        title_el = await card.query_selector(
                            ".entity-result__primary-subtitle"
                        )
                        title = (await title_el.inner_text()).strip() if title_el else ""

                        link_el = await card.query_selector(
                            "a.app-aware-link[href*='linkedin.com/in/']"
                        )
                        linkedin_url = await link_el.get_attribute("href") if link_el else None

                        if name and linkedin_url:
                            contact = await self._store_contact(
                                job_id=job_id,
                                company=company,
                                full_name=name,
                                title=title,
                                email=None,
                                linkedin_url=linkedin_url.split("?")[0],
                                confidence_score=0.7,
                                source="linkedin",
                                is_hr=True,
                            )
                            contacts.append(contact)
                    except Exception:
                        continue

            except Exception as e:
                logger.debug(f"[LinkedIn] Contact search error: {e}")
            finally:
                await browser.close()

        return contacts

    async def _store_contact(
        self,
        job_id,
        company: str,
        full_name: Optional[str],
        title: Optional[str],
        email: Optional[str],
        confidence_score: float = 0.0,
        linkedin_url: Optional[str] = None,
        source: str = "unknown",
        is_hr: bool = False,
    ) -> HRContact:
        async with get_session() as session:
            contact = HRContact(
                job_id=job_id,
                company=company,
                full_name=full_name,
                title=title,
                email=email,
                linkedin_url=linkedin_url,
                confidence_score=confidence_score,
                source=source,
            )
            session.add(contact)
            await session.flush()
            await session.refresh(contact)
        return contact

    def _extract_domain(self, job: Job) -> Optional[str]:
        """Extract company email domain from job URL or company name."""
        # Try from job URL
        if job.url:
            match = re.search(r"https?://(?:www\.)?([^/]+)", job.url)
            if match:
                domain = match.group(1)
                # Skip job board domains
                if not any(
                    bd in domain
                    for bd in ["linkedin", "stepstone", "indeed", "xing", "glassdoor", "monster"]
                ):
                    return domain

        # Try from apply URL
        if job.apply_url:
            match = re.search(r"https?://(?:www\.)?([^/]+)", job.apply_url)
            if match:
                domain = match.group(1)
                if not any(
                    bd in domain
                    for bd in ["linkedin", "stepstone", "indeed", "xing", "glassdoor", "workday", "greenhouse"]
                ):
                    return domain

        return None


def _is_hr_title(title: str) -> bool:
    return any(kw.lower() in title.lower() for kw in HR_TITLES)

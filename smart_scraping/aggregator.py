"""
Job Aggregator — orchestrates all scrapers, deduplicates, and stores jobs in DB.

Scraper priority / coverage:
  1.  Bundesagentur (BA)      — free REST API, largest German DB, no auth
  2.  JobSpy                  — LinkedIn, Indeed DE, Glassdoor unified
  3.  StepStone               — Playwright, #1 paid board in Germany
  4.  XING                    — Playwright, German professional network
  5.  Monster.de              — Playwright, major international board
  6.  Jobware.de              — HTTP/Playwright, mid/senior IT+Eng
  7.  Heise Jobs              — HTTP/Playwright, tech/software specialists
  8.  academics.de            — HTTP/Playwright, research + university
  9.  ingenieur.de            — HTTP/Playwright, engineering (VDI)
  10. Absolventa              — HTTP/Playwright, graduates + junior
  11. Karriere.at             — HTTP, Austrian/German-language jobs
  12. Jobs.de                 — HTTP/Playwright, general German board
  13. EuroEngineerJobs        — HTTP, European engineering + Experteer
"""
from __future__ import annotations

import asyncio
from typing import List, Optional, Set

from loguru import logger
from sqlalchemy import select

from core.config import settings
from core.database import get_session
from core.models import Job, JobSchema, JobSearchParams, JobSource
from scrapers.ba_scraper import scrape_bundesagentur
from scrapers.jobspy_scraper import scrape_jobspy_async
from scrapers.stepstone_scraper import scrape_stepstone
from scrapers.xing_scraper import scrape_xing
from scrapers.monster_scraper import scrape_monster
from scrapers.jobware_scraper import scrape_jobware
from scrapers.heise_scraper import scrape_heise
from scrapers.academics_scraper import scrape_academics
from scrapers.ingenieur_scraper import scrape_ingenieur
from scrapers.absolventa_scraper import scrape_absolventa
from scrapers.karriere_at_scraper import scrape_karriere_at
from scrapers.jobs_de_scraper import scrape_jobs_de
from scrapers.euroengineer_scraper import scrape_euroengineer
from scrapers.euraxess_scraper import scrape_euraxess
from scrapers.fraunhofer_scraper import scrape_fraunhofer
from scrapers.helmholtz_scraper import scrape_helmholtz
from scrapers.zeit_scraper import scrape_zeit
from scrapers.wellfound_scraper import scrape_wellfound
from scrapers.github_scraper import scrape_github_jobs

# Default sources when none specified
ALL_SOURCES = [
    # Free APIs (fastest, most reliable)
    "arbeitsagentur",
    "linkedin", "indeed", "glassdoor",
    # GitHub (open source companies hiring)
    "github",
    # Major German boards
    "stepstone", "xing", "monster",
    "jobware", "heise", "academics",
    "ingenieur", "absolventa",
    "karriere_at", "jobs_de", "euroengineer",
    # Research & academic institutions
    "euraxess", "fraunhofer", "helmholtz", "zeit_jobs",
    # Startup & international
    "wellfound",
]


class JobAggregator:
    """
    Aggregates jobs from all configured sources, deduplicates by URL,
    and persists to PostgreSQL.
    """

    def __init__(self, params: JobSearchParams):
        self.params = params

    async def run(self) -> List[Job]:
        """
        Execute all scrapers in parallel, deduplicate results, save to DB.
        Returns the list of newly inserted Job ORM objects.
        """
        sources = self.params.sources or ALL_SOURCES
        logger.info(
            f"[Aggregator] Starting scrape | positions={self.params.positions} "
            f"| locations={self.params.locations} | sources={sources}"
        )

        tasks = []

        # ── Tier 1: Free APIs (fastest, most reliable) ────────────────────────
        if "arbeitsagentur" in sources:
            tasks.append(
                scrape_bundesagentur(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                )
            )

        if "github" in sources:
            # Extract topics from positions for GitHub search
            topics = []
            for pos in self.params.positions:
                if "machine learning" in pos.lower() or "ml" in pos.lower():
                    topics.append("machine-learning")
                if "data" in pos.lower():
                    topics.append("data-science")
                if "energy" in pos.lower() or "wind" in pos.lower() or "solar" in pos.lower():
                    topics.append("energy")
                if "python" in pos.lower():
                    topics.append("python")
                if "ai" in pos.lower():
                    topics.append("artificial-intelligence")

            if not topics:  # Default topics if none detected
                topics = ["python", "machine-learning", "data-science"]

            tasks.append(
                scrape_github_jobs(
                    topics=topics,
                    location=self.params.locations[0] if self.params.locations else "Germany",
                    min_stars=50,
                    github_token=settings.github_token if hasattr(settings, 'github_token') else None,
                )
            )

        if any(s in sources for s in ["linkedin", "indeed", "glassdoor"]):
            tasks.append(
                scrape_jobspy_async(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    hours_old=self.params.hours_old,
                    results_wanted=self.params.max_results,
                )
            )

        # ── Tier 2: HTTP scrapers (fast, mostly server-side rendered) ─────────
        if "jobware" in sources:
            tasks.append(
                scrape_jobware(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "heise" in sources:
            tasks.append(
                scrape_heise(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "academics" in sources:
            tasks.append(
                scrape_academics(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "ingenieur" in sources:
            tasks.append(
                scrape_ingenieur(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "absolventa" in sources:
            tasks.append(
                scrape_absolventa(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "karriere_at" in sources:
            tasks.append(
                scrape_karriere_at(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "jobs_de" in sources:
            tasks.append(
                scrape_jobs_de(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "euroengineer" in sources:
            tasks.append(
                scrape_euroengineer(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        # ── Tier 2b: Research & academic boards (HTTP-first) ─────────────────
        if "euraxess" in sources:
            tasks.append(
                scrape_euraxess(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "fraunhofer" in sources:
            tasks.append(
                scrape_fraunhofer(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "helmholtz" in sources:
            tasks.append(
                scrape_helmholtz(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "zeit_jobs" in sources:
            tasks.append(
                scrape_zeit(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "wellfound" in sources:
            tasks.append(
                scrape_wellfound(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        # ── Tier 3: Playwright-heavy scrapers (slower, run last) ──────────────
        if "stepstone" in sources:
            tasks.append(
                scrape_stepstone(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "xing" in sources:
            tasks.append(
                scrape_xing(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        if "monster" in sources:
            tasks.append(
                scrape_monster(
                    positions=self.params.positions,
                    locations=self.params.locations,
                    max_results=self.params.max_results,
                    headless=settings.headless_browser,
                )
            )

        # Run all scrapers concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_raw: List[JobSchema] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[Aggregator] Scraper error: {result}")
            elif isinstance(result, list):
                all_raw.extend(result)

        logger.info(f"[Aggregator] Raw collected: {len(all_raw)} jobs before dedup")

        # Apply blacklists
        filtered = self._apply_filters(all_raw)
        logger.info(f"[Aggregator] After filters: {len(filtered)} jobs")

        # Deduplicate and persist
        saved = await self._save_jobs(filtered)
        logger.info(f"[Aggregator] New jobs saved to DB: {len(saved)}")

        return saved

    def _apply_filters(self, jobs: List[JobSchema]) -> List[JobSchema]:
        """Apply company and title blacklists."""
        company_bl = {c.lower() for c in self.params.company_blacklist}
        title_bl = {t.lower() for t in self.params.title_blacklist}

        filtered = []
        for job in jobs:
            if job.company.lower() in company_bl:
                continue
            if any(kw in job.title.lower() for kw in title_bl):
                continue
            filtered.append(job)
        return filtered

    async def _save_jobs(self, jobs: List[JobSchema]) -> List[Job]:
        """
        Persist jobs to DB — skip duplicates (same source + URL).
        Returns list of newly inserted Job rows.
        """
        saved: List[Job] = []

        async with get_session() as session:
            # Get existing URLs to avoid unnecessary inserts
            existing_urls: Set[str] = set()
            result = await session.execute(select(Job.url))
            for (url,) in result:
                existing_urls.add(url)

            for schema in jobs:
                if schema.url in existing_urls:
                    continue

                job = Job(
                    source=schema.source,
                    title=schema.title,
                    company=schema.company,
                    location=schema.location or "",
                    is_remote=schema.is_remote,
                    salary_min=schema.salary_min,
                    salary_max=schema.salary_max,
                    description=schema.description or "",
                    url=schema.url,
                    apply_url=schema.apply_url,
                    easy_apply=schema.easy_apply,
                    date_posted=schema.date_posted,
                    raw_data=schema.model_dump(mode="json"),
                )
                session.add(job)
                saved.append(job)
                existing_urls.add(schema.url)

            await session.flush()

        return saved

    @staticmethod
    async def get_unscored_jobs(limit: int = 100) -> List[Job]:
        """Retrieve jobs that haven't been scored yet."""
        async with get_session() as session:
            result = await session.execute(
                select(Job)
                .where(Job.match_score.is_(None))
                .order_by(Job.date_scraped.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_top_jobs(min_score: float = 7.0, limit: int = 20) -> List[Job]:
        """Retrieve top-scored jobs above the threshold."""
        async with get_session() as session:
            result = await session.execute(
                select(Job)
                .where(Job.match_score >= min_score)
                .order_by(Job.match_score.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

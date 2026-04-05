"""
LangGraph orchestration — the main multi-agent pipeline.

State machine with the following nodes:

  [START]
     │
     ▼
  parse_cv          ← Parse and store CV from PDF/LaTeX
     │
     ▼
  scrape_jobs       ← Gather jobs from all platforms
     │
     ▼
  embed_jobs        ← Generate embeddings for semantic search
     │
     ▼
  score_jobs        ← LLM scoring of each job vs CV
     │
     ▼
  review_jobs       ← (Human in loop) Review and approve jobs
     │
     ▼
  apply_jobs        ← Submit applications (LinkedIn/StepStone/Indeed)
     │
     ▼
  find_contacts     ← Find HR contacts for applied companies
     │
     ▼
  send_outreach     ← Send tailored emails to HR contacts
     │
     ▼
  [END]

Each node can be run independently. The graph maintains state across runs
so you can restart from any checkpoint.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from loguru import logger

from core.config import settings
from core.models import CVProfileSchema, Job, JobSearchParams


# ── State schema ─────────────────────────────────────────────────────────────

class PipelineState(TypedDict):
    # Input
    cv_source: str                          # Path to CV file or directory
    search_params: Dict[str, Any]           # JobSearchParams dict
    language: str                           # "de" or "en"
    dry_run: bool                           # Don't actually submit if True

    # Intermediate
    cv_profile: Optional[Dict]              # Parsed CVProfileSchema
    scraped_job_count: int
    scored_job_count: int
    top_jobs: List[Dict]                    # Jobs above threshold

    # Output
    applied_jobs: List[str]                 # job IDs
    skipped_jobs: List[str]
    contacts_found: int
    emails_sent: int
    errors: List[str]


# ── Node implementations ──────────────────────────────────────────────────────

async def node_parse_cv(state: PipelineState) -> PipelineState:
    """Parse CV from PDF or LaTeX source, store profile in DB."""
    logger.info("=== NODE: parse_cv ===")
    try:
        from cv.cv_parser import CVParser
        parser = CVParser()
        profile = await parser.parse_and_store(state["cv_source"])
        cv_schema = CVProfileSchema(
            full_name=profile.full_name,
            email=profile.email,
            phone=profile.phone,
            location=profile.location,
            linkedin_url=profile.linkedin_url,
            github_url=profile.github_url,
            summary=profile.summary,
            skills=profile.skills or [],
            languages=profile.languages or [],
            work_experience=profile.work_experience or [],
            education=profile.education or [],
            certifications=profile.certifications or [],
            raw_text=profile.raw_text,
        )
        state["cv_profile"] = cv_schema.model_dump()
        logger.info(f"CV parsed: {profile.full_name} | {len(profile.skills or [])} skills")
    except Exception as e:
        logger.error(f"[parse_cv] Error: {e}")
        state["errors"].append(f"parse_cv: {e}")
    return state


async def node_scrape_jobs(state: PipelineState) -> PipelineState:
    """Scrape jobs from all configured sources."""
    logger.info("=== NODE: scrape_jobs ===")
    try:
        from scrapers.aggregator import JobAggregator

        params_dict = state.get("search_params", {})
        params = JobSearchParams(**params_dict)
        aggregator = JobAggregator(params)
        saved_jobs = await aggregator.run()

        state["scraped_job_count"] = len(saved_jobs)
        logger.info(f"Scraped and saved {len(saved_jobs)} new jobs")
    except Exception as e:
        logger.error(f"[scrape_jobs] Error: {e}")
        state["errors"].append(f"scrape_jobs: {e}")
    return state


async def node_embed_jobs(state: PipelineState) -> PipelineState:
    """Generate vector embeddings for all unembedded jobs."""
    logger.info("=== NODE: embed_jobs ===")
    try:
        from matching.embedder import embed_and_store_all_jobs
        count = await embed_and_store_all_jobs()
        logger.info(f"Embedded {count} jobs")
    except Exception as e:
        logger.error(f"[embed_jobs] Error: {e}")
        state["errors"].append(f"embed_jobs: {e}")
    return state


async def node_score_jobs(state: PipelineState) -> PipelineState:
    """Score all unscored jobs using LLM."""
    logger.info("=== NODE: score_jobs ===")
    try:
        from matching.scorer import score_all_unscored_jobs

        if not state.get("cv_profile"):
            raise ValueError("CV profile not available for scoring")

        cv_profile = CVProfileSchema(**state["cv_profile"])
        scored = await score_all_unscored_jobs(cv_profile, batch_size=50)
        state["scored_job_count"] = scored
        logger.info(f"Scored {scored} jobs")

        # Load top jobs for next steps
        from scrapers.aggregator import JobAggregator
        top = await JobAggregator.get_top_jobs(
            min_score=settings.auto_apply_threshold, limit=20
        )
        state["top_jobs"] = [
            {
                "id": str(j.id),
                "title": j.title,
                "company": j.company,
                "score": j.match_score,
                "url": j.url,
                "source": j.source.value if j.source else "unknown",
                "easy_apply": j.easy_apply,
            }
            for j in top
        ]
        logger.info(f"Top jobs for application: {len(top)}")
    except Exception as e:
        logger.error(f"[score_jobs] Error: {e}")
        state["errors"].append(f"score_jobs: {e}")
    return state


async def node_apply_jobs(state: PipelineState) -> PipelineState:
    """Apply to top-scored jobs using platform-specific appliers."""
    logger.info("=== NODE: apply_jobs ===")
    if not state.get("cv_profile"):
        return state

    cv_profile = CVProfileSchema(**state["cv_profile"])
    top_jobs = state.get("top_jobs", [])

    if not top_jobs:
        logger.info("[apply_jobs] No jobs to apply to")
        return state

    from sqlalchemy import select
    from core.database import get_session
    from core.models import Job as JobModel
    from applications.linkedin_applier import LinkedInApplier
    from applications.stepstone_applier import StepStoneApplier
    from applications.indeed_applier import IndeedApplier
    from cover_letter.generator import CoverLetterGenerator

    cover_gen = CoverLetterGenerator(cv_profile)
    dry_run = state.get("dry_run", False)
    language = state.get("language", "de")

    applied = []
    skipped = []

    for job_dict in top_jobs:
        job_id = job_dict["id"]
        try:
            async with get_session() as session:
                job = await session.get(JobModel, job_id)
                if not job:
                    continue

            # Generate cover letter
            try:
                cover = await cover_gen.generate_and_store(job, language)
                cover_path = cover.pdf_path
            except Exception as e:
                logger.warning(f"[apply_jobs] Cover letter failed for {job.title}: {e}")
                cover_path = None

            # Apply based on source
            source = job_dict.get("source", "")
            success = False

            if source == "linkedin" or job_dict.get("easy_apply"):
                async with LinkedInApplier(cv_profile) as applier:
                    if await applier.login():
                        success = await applier.apply_to_job(job, cover_path, dry_run)

            elif source == "stepstone":
                applier = StepStoneApplier(cv_profile)
                success = await applier.apply_to_job(job, cover_path, dry_run)

            elif source in ("indeed", "arbeitsagentur"):
                applier = IndeedApplier(cv_profile)
                success = await applier.apply_to_job(job, cover_path, dry_run)

            if success:
                applied.append(job_id)
            else:
                skipped.append(job_id)

        except Exception as e:
            logger.error(f"[apply_jobs] Error applying to {job_dict.get('title')}: {e}")
            state["errors"].append(f"apply: {job_id}: {e}")
            skipped.append(job_id)

    state["applied_jobs"] = applied
    state["skipped_jobs"] = skipped
    logger.info(f"Applied: {len(applied)} | Skipped: {len(skipped)}")
    return state


async def node_find_contacts(state: PipelineState) -> PipelineState:
    """Find HR contacts for companies where we applied."""
    logger.info("=== NODE: find_contacts ===")
    if not state.get("applied_jobs"):
        return state

    from core.database import get_session
    from core.models import Job as JobModel
    from outreach.contact_finder import ContactFinder

    finder = ContactFinder()
    total_contacts = 0

    for job_id in state["applied_jobs"]:
        try:
            async with get_session() as session:
                job = await session.get(JobModel, job_id)
                if not job:
                    continue
            contacts = await finder.find_for_job(job)
            total_contacts += len(contacts)
        except Exception as e:
            logger.error(f"[find_contacts] Error for job {job_id}: {e}")

    state["contacts_found"] = total_contacts
    logger.info(f"Found {total_contacts} HR contacts")
    return state


async def node_send_outreach(state: PipelineState) -> PipelineState:
    """Send personalized emails to found HR contacts."""
    logger.info("=== NODE: send_outreach ===")
    if not state.get("cv_profile") or not state.get("applied_jobs"):
        return state

    from sqlalchemy import select
    from core.database import get_session
    from core.models import HRContact, Job as JobModel
    from outreach.emailer import Emailer

    cv_profile = CVProfileSchema(**state["cv_profile"])
    emailer = Emailer(cv_profile)
    dry_run = state.get("dry_run", False)
    language = state.get("language", "de")
    sent = 0

    for job_id in state["applied_jobs"]:
        try:
            async with get_session() as session:
                job = await session.get(JobModel, job_id)
                if not job:
                    continue
                result = await session.execute(
                    select(HRContact).where(
                        HRContact.job_id == job_id,
                        HRContact.email.isnot(None),
                    ).limit(1)
                )
                contact = result.scalar_one_or_none()

            if not contact:
                logger.debug(f"[send_outreach] No email contact for job {job_id}")
                continue

            await emailer.send_email(
                job=job,
                contact=contact,
                email_type="application",
                language=language,
                dry_run=dry_run,
            )
            sent += 1

        except Exception as e:
            logger.error(f"[send_outreach] Error for job {job_id}: {e}")

    state["emails_sent"] = sent
    logger.info(f"Sent {sent} emails")
    return state


# ── Graph builder ─────────────────────────────────────────────────────────────

class JobPredatorGraph:
    """
    Main orchestration class. Can be run as a full pipeline or step-by-step.
    """

    def __init__(
        self,
        cv_source: str,
        positions: List[str],
        locations: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        language: str = "de",
        dry_run: bool = False,
    ):
        self.initial_state = PipelineState(
            cv_source=cv_source,
            search_params=JobSearchParams(
                positions=positions,
                locations=locations or ["Deutschland", "Berlin", "Munich", "Hamburg"],
                sources=sources or ["linkedin", "indeed", "stepstone", "arbeitsagentur"],
                max_results=settings.scrape_max_results,
                hours_old=settings.scrape_hours_old,
            ).model_dump(),
            language=language,
            dry_run=dry_run,
            cv_profile=None,
            scraped_job_count=0,
            scored_job_count=0,
            top_jobs=[],
            applied_jobs=[],
            skipped_jobs=[],
            contacts_found=0,
            emails_sent=0,
            errors=[],
        )

    async def run_full_pipeline(self) -> PipelineState:
        """Execute the complete pipeline from CV parsing to outreach."""
        state = self.initial_state.copy()
        nodes = [
            node_parse_cv,
            node_scrape_jobs,
            node_embed_jobs,
            node_score_jobs,
            node_apply_jobs,
            node_find_contacts,
            node_send_outreach,
        ]
        for node in nodes:
            logger.info(f"Running node: {node.__name__}")
            state = await node(state)
            if len(state.get("errors", [])) > 5:
                logger.error("Too many errors, stopping pipeline")
                break
        return state

    async def run_until(self, stop_before: str) -> PipelineState:
        """Run pipeline up to (but not including) a specific node."""
        node_map = {
            "parse_cv": node_parse_cv,
            "scrape_jobs": node_scrape_jobs,
            "embed_jobs": node_embed_jobs,
            "score_jobs": node_score_jobs,
            "apply_jobs": node_apply_jobs,
            "find_contacts": node_find_contacts,
            "send_outreach": node_send_outreach,
        }
        state = self.initial_state.copy()
        for name, node in node_map.items():
            if name == stop_before:
                break
            state = await node(state)
        return state

    def print_summary(self, state: PipelineState) -> None:
        """Print a human-readable pipeline summary."""
        from rich.console import Console
        from rich.table import Table

        console = Console()
        console.print("\n[bold green]═══ JobPredator Pipeline Summary ═══[/bold green]")
        console.print(f"  Jobs scraped:      {state['scraped_job_count']}")
        console.print(f"  Jobs scored:       {state['scored_job_count']}")
        console.print(f"  Jobs applied:      {len(state['applied_jobs'])}")
        console.print(f"  Jobs skipped:      {len(state['skipped_jobs'])}")
        console.print(f"  HR contacts found: {state['contacts_found']}")
        console.print(f"  Emails sent:       {state['emails_sent']}")

        if state.get("top_jobs"):
            table = Table(title="Top Matching Jobs")
            table.add_column("Score", style="green")
            table.add_column("Title")
            table.add_column("Company")
            table.add_column("Source")
            for job in state["top_jobs"][:10]:
                table.add_row(
                    f"{job.get('score', 0):.1f}",
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("source", ""),
                )
            console.print(table)

        if state.get("errors"):
            console.print(f"\n[red]Errors ({len(state['errors'])}):[/red]")
            for err in state["errors"]:
                console.print(f"  • {err}")

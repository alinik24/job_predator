"""
FastAPI REST API for JobPredator.

Endpoints:
  POST /pipeline/run         — Run full pipeline
  POST /pipeline/scrape      — Scrape jobs only
  POST /pipeline/score       — Score jobs only
  GET  /jobs                 — List all jobs with filters
  GET  /jobs/{id}            — Get single job
  GET  /jobs/top             — Get top-scored jobs
  POST /apply/{job_id}       — Apply to a specific job
  GET  /applications         — List all applications
  GET  /cover-letters        — List generated cover letters
  GET  /contacts             — List found HR contacts
  POST /cv/upload            — Upload CV file
  GET  /cv/profile           — Get parsed CV profile
  POST /documents/upload     — Upload supporting document
  GET  /documents            — List all documents
  GET  /stats                — Dashboard statistics
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select

from core.config import settings
from core.database import get_session, init_db
from core.models import (
    Application,
    ApplicationStatus,
    CoverLetter,
    CVProfile,
    Document,
    DocumentType,
    HRContact,
    Job,
    JobSearchParams,
    JobSource,
    OutreachMessage,
)

app = FastAPI(
    title="JobPredator API",
    description="AI-powered job hunting and application submission platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await init_db()
    Path(settings.documents_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    logger.info("JobPredator API started")


# ── Request/Response models ───────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    positions: List[str]
    locations: Optional[List[str]] = None
    sources: Optional[List[str]] = None
    language: str = "de"
    dry_run: bool = True
    stop_before: Optional[str] = None  # "apply_jobs", "send_outreach", etc.


class ApplyRequest(BaseModel):
    cover_letter_language: str = "de"
    dry_run: bool = True


# ── Pipeline endpoints ────────────────────────────────────────────────────────

@app.post("/pipeline/run")
async def run_pipeline(request: PipelineRequest, background_tasks: BackgroundTasks):
    """
    Start the full pipeline as a background task.
    Returns immediately with a task ID.
    """
    cv_profile = await _get_latest_cv_profile()
    if not cv_profile:
        raise HTTPException(400, "No CV profile found. Upload your CV first.")

    from agents.graph import JobPredatorGraph

    async def _run():
        graph = JobPredatorGraph(
            cv_source=cv_profile.source_file or settings.cv_pdf_path or "",
            positions=request.positions,
            locations=request.locations,
            sources=request.sources,
            language=request.language,
            dry_run=request.dry_run,
        )
        if request.stop_before:
            state = await graph.run_until(request.stop_before)
        else:
            state = await graph.run_full_pipeline()
        graph.print_summary(state)
        return state

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Pipeline running in background"}


@app.post("/pipeline/scrape")
async def scrape_only(request: PipelineRequest):
    """Scrape jobs from all sources and return counts."""
    from scrapers.aggregator import JobAggregator

    params = JobSearchParams(
        positions=request.positions,
        locations=request.locations or ["Deutschland"],
        sources=request.sources or ["linkedin", "indeed", "stepstone", "arbeitsagentur"],
        max_results=settings.scrape_max_results,
    )
    aggregator = JobAggregator(params)
    jobs = await aggregator.run()
    return {"scraped": len(jobs), "positions": request.positions}


@app.post("/pipeline/score")
async def score_only():
    """Score all unscored jobs. Returns count scored."""
    cv_profile_orm = await _get_latest_cv_profile()
    if not cv_profile_orm:
        raise HTTPException(400, "No CV profile found")

    from core.models import CVProfileSchema
    from matching.scorer import score_all_unscored_jobs

    cv = CVProfileSchema(
        full_name=cv_profile_orm.full_name,
        email=cv_profile_orm.email,
        skills=cv_profile_orm.skills or [],
        work_experience=cv_profile_orm.work_experience or [],
        education=cv_profile_orm.education or [],
        raw_text=cv_profile_orm.raw_text,
    )
    count = await score_all_unscored_jobs(cv, batch_size=50)
    return {"scored": count}


# ── Jobs endpoints ────────────────────────────────────────────────────────────

@app.get("/jobs")
async def list_jobs(
    status: Optional[str] = None,
    source: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    async with get_session() as session:
        query = select(Job)
        if status:
            query = query.where(Job.status == status)
        if source:
            query = query.where(Job.source == source)
        if min_score is not None:
            query = query.where(Job.match_score >= min_score)
        query = query.order_by(Job.match_score.desc().nullslast()).offset(offset).limit(limit)
        result = await session.execute(query)
        jobs = result.scalars().all()

    return [_job_to_dict(j) for j in jobs]


@app.get("/jobs/top")
async def top_jobs(min_score: float = 7.0, limit: int = 20):
    from scrapers.aggregator import JobAggregator
    jobs = await JobAggregator.get_top_jobs(min_score, limit)
    return [_job_to_dict(j) for j in jobs]


@app.get("/jobs/{job_id}")
async def get_job(job_id: UUID):
    async with get_session() as session:
        job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_to_dict(job)


# ── Application endpoints ─────────────────────────────────────────────────────

@app.post("/apply/{job_id}")
async def apply_to_job(job_id: UUID, request: ApplyRequest, background_tasks: BackgroundTasks):
    """Apply to a specific job."""
    async with get_session() as session:
        job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    cv_profile_orm = await _get_latest_cv_profile()
    if not cv_profile_orm:
        raise HTTPException(400, "No CV profile found")

    async def _apply():
        from core.models import CVProfileSchema
        from cover_letter.generator import CoverLetterGenerator
        from applications.linkedin_applier import LinkedInApplier
        from applications.stepstone_applier import StepStoneApplier
        from applications.indeed_applier import IndeedApplier

        cv = CVProfileSchema(
            full_name=cv_profile_orm.full_name,
            email=cv_profile_orm.email,
            skills=cv_profile_orm.skills or [],
            work_experience=cv_profile_orm.work_experience or [],
            education=cv_profile_orm.education or [],
            languages=cv_profile_orm.languages or [],
            raw_text=cv_profile_orm.raw_text,
        )

        cover_gen = CoverLetterGenerator(cv)
        cover = await cover_gen.generate_and_store(job, request.cover_letter_language)

        if job.source in (JobSource.LINKEDIN,) or job.easy_apply:
            async with LinkedInApplier(cv) as applier:
                await applier.login()
                await applier.apply_to_job(job, cover.pdf_path, request.dry_run)
        elif job.source == JobSource.STEPSTONE:
            applier = StepStoneApplier(cv)
            await applier.apply_to_job(job, cover.pdf_path, request.dry_run)
        else:
            applier = IndeedApplier(cv)
            await applier.apply_to_job(job, cover.pdf_path, request.dry_run)

    background_tasks.add_task(_apply)
    return {"status": "started", "job_id": str(job_id), "dry_run": request.dry_run}


@app.get("/applications")
async def list_applications():
    async with get_session() as session:
        result = await session.execute(
            select(Application).order_by(Application.applied_at.desc())
        )
        apps = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "job_id": str(a.job_id),
            "status": a.status.value,
            "applied_at": a.applied_at.isoformat() if a.applied_at else None,
        }
        for a in apps
    ]


# ── CV endpoints ──────────────────────────────────────────────────────────────

@app.post("/cv/upload")
async def upload_cv(file: UploadFile = File(...)):
    """Upload and parse a CV file (PDF, DOCX, or .tex)."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".tex", ".latex"):
        raise HTTPException(400, "Supported formats: PDF, DOCX, .tex")

    save_path = Path(settings.documents_dir) / file.filename
    save_path.write_bytes(await file.read())

    from cv.cv_parser import CVParser
    parser = CVParser()
    profile = await parser.parse_and_store(save_path)

    return {
        "id": str(profile.id),
        "name": profile.full_name,
        "skills_count": len(profile.skills or []),
        "experience_count": len(profile.work_experience or []),
    }


@app.get("/cv/profile")
async def get_cv_profile():
    """Get the most recently parsed CV profile."""
    profile = await _get_latest_cv_profile()
    if not profile:
        raise HTTPException(404, "No CV profile found. Upload your CV first.")
    return {
        "id": str(profile.id),
        "full_name": profile.full_name,
        "email": profile.email,
        "location": profile.location,
        "skills": profile.skills,
        "languages": profile.languages,
        "work_experience": profile.work_experience,
        "education": profile.education,
        "certifications": profile.certifications,
    }


# ── Documents endpoints ───────────────────────────────────────────────────────

@app.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = "other",
    name: Optional[str] = None,
):
    """Upload a supporting document (certificate, work reference, etc.)."""
    save_path = Path(settings.documents_dir) / file.filename
    save_path.write_bytes(await file.read())

    from documents.store import DocumentStore

    try:
        dt = DocumentType(doc_type)
    except ValueError:
        dt = DocumentType.OTHER

    store = DocumentStore()
    doc = await store.upload(save_path, dt, name)
    return {"id": str(doc.id), "name": doc.name, "type": doc.doc_type.value}


@app.get("/documents")
async def list_documents():
    from documents.store import DocumentStore
    store = DocumentStore()
    docs = await store.get_all()
    return [
        {
            "id": str(d.id),
            "name": d.name,
            "type": d.doc_type.value,
            "filename": d.filename,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
        }
        for d in docs
    ]


# ── Contacts & outreach endpoints ─────────────────────────────────────────────

@app.get("/contacts")
async def list_contacts():
    async with get_session() as session:
        result = await session.execute(
            select(HRContact).order_by(HRContact.found_at.desc()).limit(100)
        )
        contacts = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "company": c.company,
            "name": c.full_name,
            "title": c.title,
            "email": c.email,
            "linkedin_url": c.linkedin_url,
            "confidence": c.confidence_score,
            "source": c.source,
        }
        for c in contacts
    ]


# ── Stats endpoint ────────────────────────────────────────────────────────────

@app.get("/stats")
async def stats():
    async with get_session() as session:
        total_jobs = (await session.execute(select(func.count(Job.id)))).scalar()
        applied = (
            await session.execute(
                select(func.count(Application.id)).where(
                    Application.status == ApplicationStatus.APPLIED
                )
            )
        ).scalar()
        total_contacts = (await session.execute(select(func.count(HRContact.id)))).scalar()
        total_emails = (
            await session.execute(
                select(func.count(OutreachMessage.id)).where(
                    OutreachMessage.status == "sent"
                )
            )
        ).scalar()
        avg_score = (
            await session.execute(
                select(func.avg(Job.match_score)).where(Job.match_score.isnot(None))
            )
        ).scalar()

    return {
        "total_jobs": total_jobs,
        "applied": applied,
        "hr_contacts_found": total_contacts,
        "emails_sent": total_emails,
        "average_match_score": round(avg_score or 0, 2),
    }


# ── Cover letters ─────────────────────────────────────────────────────────────

@app.get("/cover-letters")
async def list_cover_letters():
    async with get_session() as session:
        result = await session.execute(
            select(CoverLetter).order_by(CoverLetter.generated_at.desc()).limit(50)
        )
        letters = result.scalars().all()
    return [
        {
            "id": str(cl.id),
            "job_id": str(cl.job_id),
            "language": cl.language,
            "generated_at": cl.generated_at.isoformat() if cl.generated_at else None,
            "has_pdf": cl.pdf_path is not None,
            "has_docx": cl.docx_path is not None,
        }
        for cl in letters
    ]


@app.get("/cover-letters/{letter_id}/download")
async def download_cover_letter(letter_id: UUID, format: str = "pdf"):
    async with get_session() as session:
        letter = await session.get(CoverLetter, letter_id)
    if not letter:
        raise HTTPException(404, "Cover letter not found")

    path = letter.pdf_path if format == "pdf" else letter.docx_path
    if not path or not Path(path).exists():
        raise HTTPException(404, f"File not found: {format}")

    return FileResponse(path, media_type="application/octet-stream", filename=Path(path).name)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_latest_cv_profile() -> Optional[CVProfile]:
    async with get_session() as session:
        result = await session.execute(
            select(CVProfile).order_by(CVProfile.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()


def _job_to_dict(job: Job) -> dict:
    return {
        "id": str(job.id),
        "source": job.source.value if job.source else None,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "is_remote": job.is_remote,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "url": job.url,
        "easy_apply": job.easy_apply,
        "date_posted": job.date_posted.isoformat() if job.date_posted else None,
        "match_score": job.match_score,
        "match_reasons": job.match_reasons,
        "status": job.status.value if job.status else None,
    }

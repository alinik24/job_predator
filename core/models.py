"""
All SQLAlchemy ORM models + Pydantic schemas for the JobPredator system.

Tables:
  - jobs              : scraped job postings
  - cv_profile        : parsed structured CV data
  - documents         : uploaded user documents (CV, certificates, etc.)
  - applications      : application tracking
  - cover_letters     : generated cover letters per job
  - hr_contacts       : found HR / recruiter contacts
  - outreach_messages : sent emails / LinkedIn messages
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, Field
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from core.database import Base


# ── Enums ────────────────────────────────────────────────────────────────────

class ApplicationStatus(str, enum.Enum):
    DISCOVERED = "discovered"      # scraped, not yet scored
    SCORED = "scored"              # LLM match score assigned
    QUEUED = "queued"              # approved for application
    APPLYING = "applying"          # browser automation in progress
    APPLIED = "applied"            # successfully submitted
    COVER_SENT = "cover_sent"      # follow-up email sent to HR
    REJECTED = "rejected"          # rejection received
    INTERVIEW = "interview"        # interview scheduled
    OFFER = "offer"                # offer received
    SKIPPED = "skipped"            # below threshold / blacklisted


class JobSource(str, enum.Enum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    STEPSTONE = "stepstone"
    XING = "xing"
    GLASSDOOR = "glassdoor"
    ARBEITSAGENTUR = "arbeitsagentur"
    MONSTER = "monster"
    JOBWARE = "jobware"
    KARRIERE_AT = "karriere_at"
    HEISE = "heise"
    ACADEMICS = "academics"
    INGENIEUR = "ingenieur"
    ABSOLVENTA = "absolventa"
    JOBS_DE = "jobs_de"
    JOBSCOUT24 = "jobscout24"
    EUROENGINEER = "euroengineer"
    # Research & academic institutions
    EURAXESS = "euraxess"
    FRAUNHOFER = "fraunhofer"
    MAXPLANCK = "maxplanck"
    HELMHOLTZ = "helmholtz"
    ZEIT_JOBS = "zeit_jobs"
    # Startup / international
    WELLFOUND = "wellfound"
    OTTA = "otta"
    GERMANTECHJOBS = "germantechjobs"
    OTHER = "other"


class DocumentType(str, enum.Enum):
    CV = "cv"
    COVER_LETTER_TEMPLATE = "cover_letter_template"
    CERTIFICATE = "certificate"
    DEGREE = "degree"
    WORK_REFERENCE = "work_reference"
    OTHER = "other"


class OutreachChannel(str, enum.Enum):
    EMAIL = "email"
    LINKEDIN_MESSAGE = "linkedin_message"
    LINKEDIN_INMAIL = "linkedin_inmail"


# ── ORM Models ───────────────────────────────────────────────────────────────

class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_id = Column(String(512), nullable=True)     # platform's own job ID
    source = Column(String(64), nullable=False)
    title = Column(String(512), nullable=False)
    company = Column(String(256), nullable=False)
    location = Column(String(256), nullable=True)
    is_remote = Column(Boolean, default=False)
    job_type = Column(String(64), nullable=True)          # full-time, part-time, etc.
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    salary_currency = Column(String(8), default="EUR")
    description = Column(Text, nullable=True)
    requirements = Column(Text, nullable=True)
    url = Column(String(1024), nullable=False)
    apply_url = Column(String(1024), nullable=True)
    easy_apply = Column(Boolean, default=False)
    date_posted = Column(DateTime, nullable=True)
    date_scraped = Column(DateTime, server_default=func.now())
    match_score = Column(Float, nullable=True)           # LLM 0-10 score
    match_reasons = Column(JSON, nullable=True)          # {"pros": [...], "cons": [...]}
    embedding = Column(Vector(384), nullable=True)       # sentence-transformer embedding
    status = Column(String(32), default="discovered")
    raw_data = Column(JSON, nullable=True)               # original scraped data

    applications = relationship("Application", back_populates="job")
    cover_letters = relationship("CoverLetter", back_populates="job")

    __table_args__ = (
        UniqueConstraint("source", "url", name="uq_job_source_url"),
        Index("ix_jobs_match_score", "match_score"),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_source", "source"),
    )


class CVProfile(Base):
    __tablename__ = "cv_profile"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    full_name = Column(String(256), nullable=True)
    email = Column(String(256), nullable=True)
    phone = Column(String(64), nullable=True)
    location = Column(String(256), nullable=True)
    linkedin_url = Column(String(512), nullable=True)
    github_url = Column(String(512), nullable=True)
    summary = Column(Text, nullable=True)
    skills = Column(JSON, nullable=True)                 # list of strings
    languages = Column(JSON, nullable=True)              # [{"lang": "German", "level": "B2"}]
    work_experience = Column(JSON, nullable=True)        # list of experience dicts
    education = Column(JSON, nullable=True)              # list of education dicts
    certifications = Column(JSON, nullable=True)
    raw_text = Column(Text, nullable=True)               # full CV text (for LLM context)
    embedding = Column(Vector(384), nullable=True)       # profile embedding
    source_file = Column(String(512), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    doc_type = Column(String(64), nullable=False)
    name = Column(String(256), nullable=False)
    filename = Column(String(256), nullable=False)
    content_text = Column(Text, nullable=True)           # extracted text
    content_bytes = Column(Text, nullable=True)          # base64-encoded binary
    embedding = Column(Vector(384), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    uploaded_at = Column(DateTime, server_default=func.now())


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    status = Column(String(32), default="queued")
    cover_letter_id = Column(UUID(as_uuid=True), ForeignKey("cover_letters.id"), nullable=True)
    applied_at = Column(DateTime, nullable=True)
    platform_application_id = Column(String(256), nullable=True)
    form_answers = Column(JSON, nullable=True)           # {question: answer}
    notes = Column(Text, nullable=True)
    error_log = Column(Text, nullable=True)

    job = relationship("Job", back_populates="applications")
    cover_letter = relationship("CoverLetter", back_populates="application")

    __table_args__ = (
        Index("ix_applications_status", "status"),
        Index("ix_applications_job_id", "job_id"),
    )


class CoverLetter(Base):
    __tablename__ = "cover_letters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(String(32), default="v1")
    language = Column(String(8), default="de")
    generated_at = Column(DateTime, server_default=func.now())
    docx_path = Column(String(512), nullable=True)
    pdf_path = Column(String(512), nullable=True)

    job = relationship("Job", back_populates="cover_letters")
    application = relationship("Application", back_populates="cover_letter", uselist=False)


class HRContact(Base):
    __tablename__ = "hr_contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    company = Column(String(256), nullable=False)
    full_name = Column(String(256), nullable=True)
    title = Column(String(256), nullable=True)
    email = Column(String(256), nullable=True)
    linkedin_url = Column(String(512), nullable=True)
    confidence_score = Column(Float, nullable=True)      # Hunter.io confidence
    source = Column(String(64), nullable=True)           # "hunter.io", "linkedin", etc.
    found_at = Column(DateTime, server_default=func.now())

    outreach_messages = relationship("OutreachMessage", back_populates="contact")


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("hr_contacts.id"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    channel = Column(String(32), nullable=False)
    subject = Column(String(512), nullable=True)
    body = Column(Text, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="draft")         # draft, sent, replied

    contact = relationship("HRContact", back_populates="outreach_messages")


class UserMemory(Base):
    """
    Single-row (per-user) persistent memory: confirmed skills, preferences,
    company blacklist, and the preference embedding used for adaptive scoring.
    """
    __tablename__ = "user_memory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # {"Python": "confirmed", "Spark": "learning", "COBOL": "no"}
    skill_claims = Column(JSON, default=dict)
    # {"Data Engineer": "preferred", "DevOps": "avoid"}
    position_preferences = Column(JSON, default=dict)
    company_blacklist = Column(JSON, default=list)
    # {"Energy": "preferred", "Defense": "avoid"}
    industry_preferences = Column(JSON, default=dict)
    # {"Berlin": "preferred", "remote": "required"}
    location_preferences = Column(JSON, default=dict)
    min_salary = Column(Float, nullable=True)
    remote_preference = Column(String(16), default="flexible")
    notes = Column(Text, nullable=True)
    # Centroid of liked-job embeddings — updated after each feedback round
    preference_embedding = Column(Vector(384), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class JobFeedback(Base):
    """
    User's explicit decision on a job — the core learning signal.
    decisions: interested | apply | skip | not_interested |
               applied_manually | got_interview | got_offer | rejected_by_company
    """
    __tablename__ = "job_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    decision = Column(String(32), nullable=False)
    user_score = Column(Float, nullable=True)         # overrides LLM score if set
    reason = Column(Text, nullable=True)
    job_embedding_snapshot = Column(Vector(384), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    job = relationship("Job", foreign_keys=[job_id])

    __table_args__ = (
        Index("ix_job_feedback_job_id", "job_id"),
        Index("ix_job_feedback_decision", "decision"),
    )


class SkillGap(Base):
    """
    Aggregated skill gaps across all top-scored jobs.
    Tracks what the market wants that the CV doesn't yet contain,
    and whether the user has claimed they actually have it.
    """
    __tablename__ = "skill_gaps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    skill_name = Column(String(256), nullable=False, unique=True)
    frequency = Column(BigInteger, default=1)         # how many jobs needed it
    job_ids = Column(JSON, default=list)               # which job IDs mentioned it
    # null | "have_it" | "learning" | "not_interested"
    user_claim = Column(String(32), nullable=True)
    cv_suggestion = Column(Text, nullable=True)        # suggested LaTeX snippet
    first_seen = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_skill_gaps_frequency", "frequency"),
    )


class SearchSession(Base):
    """
    Records each search round — positions, results, user-approved keywords.
    Enables tracking of what was searched and how results improved over time.
    """
    __tablename__ = "search_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    positions_used = Column(JSON, nullable=False)
    positions_suggested = Column(JSON, default=list)
    positions_approved = Column(JSON, default=list)
    sources = Column(JSON, default=list)
    jobs_found = Column(BigInteger, default=0)
    jobs_scored = Column(BigInteger, default=0)
    jobs_above_threshold = Column(BigInteger, default=0)
    top_score = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class JobSkillsMatrix(Base):
    """
    Per-job skills analysis: which required skills the user has vs. is missing,
    niche keywords to learn, which CV sections to emphasise, ATS score estimate.
    One row per job (unique on job_id).
    """
    __tablename__ = "job_skills_matrix"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # [{skill, type: must/nice, category: tech/soft/domain, user_has, evidence, importance}]
    required_skills = Column(JSON, default=list)
    # [{skill, gap_severity, workaround}]
    missing_skills = Column(JSON, default=list)
    # [{keyword, niche_context, why_important, learn_resource}]
    niche_keywords = Column(JSON, default=list)
    # ["Thesis: ...", "Fraunhofer experience", ...]
    cv_sections_to_highlight = Column(JSON, default=list)
    # ["Master thesis project", "Fraunhofer internship", ...]
    projects_to_mention = Column(JSON, default=list)
    # Estimated ATS match score (0-10)
    ats_score = Column(Float, nullable=True)
    # ["energy management system", "EMS", "SCADA"] — terms to add to CV/letter
    ats_keywords_to_add = Column(JSON, default=list)
    # ["Prepare: power flow algorithms", ...]
    interview_topics = Column(JSON, default=list)
    # 2-3 sentence overall summary
    analysis_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    job = relationship("Job", foreign_keys=[job_id])

    __table_args__ = (
        Index("ix_job_skills_matrix_job_id", "job_id"),
    )


class CoverLetterStyle(Base):
    """
    Learned writing style from the user's existing cover letters.
    Single row per user — updated each time 'learn-style' is run.
    """
    __tablename__ = "cover_letter_style"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # LLM-extracted tone description
    style_summary = Column(Text, nullable=True)
    # Characteristic phrases/patterns
    tone_markers = Column(JSON, default=list)
    # Typical paragraph structure
    structure_pattern = Column(JSON, default=list)
    # Which strengths appear repeatedly
    strengths_highlighted = Column(JSON, default=list)
    # Example opening sentences
    sample_openings = Column(JSON, default=list)
    # Example closing sentences
    sample_closings = Column(JSON, default=list)
    # Full raw analysis dict from LLM
    raw_analysis = Column(JSON, nullable=True)
    # How many cover letters were analysed
    sample_count = Column(Float, default=0)       # using Float to avoid Integer import
    # Source file names
    source_files = Column(JSON, default=list)
    learned_at = Column(DateTime, server_default=func.now())


# ── Pydantic Schemas (API / service layer) ───────────────────────────────────

class JobSchema(BaseModel):
    id: Optional[str] = None
    source: str
    title: str
    company: str
    location: Optional[str] = None
    is_remote: bool = False
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    description: Optional[str] = None
    url: str
    apply_url: Optional[str] = None
    easy_apply: bool = False
    date_posted: Optional[datetime] = None
    match_score: Optional[float] = None
    status: str = ApplicationStatus.DISCOVERED

    class Config:
        from_attributes = True


class CVProfileSchema(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    summary: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    languages: List[Dict[str, str]] = Field(default_factory=list)
    work_experience: List[Dict[str, Any]] = Field(default_factory=list)
    education: List[Dict[str, Any]] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    raw_text: Optional[str] = None


class JobSearchParams(BaseModel):
    positions: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default=["Deutschland"])
    remote_ok: bool = True
    hours_old: int = 72
    max_results: int = 50
    sources: List[str] = Field(
        default_factory=lambda: [
            # Free APIs & aggregators
            "arbeitsagentur",
            "linkedin", "indeed", "glassdoor",
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
    )
    company_blacklist: List[str] = Field(default_factory=list)
    title_blacklist: List[str] = Field(default_factory=list)
    min_match_score: float = 6.0

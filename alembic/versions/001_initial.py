"""Initial schema — all JobPredator tables with pgvector

Revision ID: 001
Revises:
Create Date: 2026-03-28

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── jobs ─────────────────────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("external_id", sa.String(512), nullable=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("company", sa.String(256), nullable=False),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("is_remote", sa.Boolean(), default=False),
        sa.Column("job_type", sa.String(64), nullable=True),
        sa.Column("salary_min", sa.Float(), nullable=True),
        sa.Column("salary_max", sa.Float(), nullable=True),
        sa.Column("salary_currency", sa.String(8), default="EUR"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("requirements", sa.Text(), nullable=True),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("apply_url", sa.String(1024), nullable=True),
        sa.Column("easy_apply", sa.Boolean(), default=False),
        sa.Column("date_posted", sa.DateTime(), nullable=True),
        sa.Column("date_scraped", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("match_reasons", postgresql.JSONB(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),  # stored as vector(384)
        sa.Column("status", sa.String(32), default="discovered"),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("source", "url", name="uq_job_source_url"),
    )
    op.execute("ALTER TABLE jobs ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384)")
    op.create_index("ix_jobs_match_score", "jobs", ["match_score"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_source", "jobs", ["source"])
    op.execute("CREATE INDEX ix_jobs_embedding ON jobs USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")

    # ── cv_profile ────────────────────────────────────────────────────────────
    op.create_table(
        "cv_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("full_name", sa.String(256), nullable=True),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("linkedin_url", sa.String(512), nullable=True),
        sa.Column("github_url", sa.String(512), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("skills", postgresql.JSONB(), nullable=True),
        sa.Column("languages", postgresql.JSONB(), nullable=True),
        sa.Column("work_experience", postgresql.JSONB(), nullable=True),
        sa.Column("education", postgresql.JSONB(), nullable=True),
        sa.Column("certifications", postgresql.JSONB(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("source_file", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), onupdate=sa.func.now()),
    )
    op.execute("ALTER TABLE cv_profile ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384)")

    # ── documents ─────────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("doc_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_bytes", sa.Text(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE documents ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384)")

    # ── cover_letters ─────────────────────────────────────────────────────────
    op.create_table(
        "cover_letters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.String(32), default="v1"),
        sa.Column("language", sa.String(8), default="de"),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("docx_path", sa.String(512), nullable=True),
        sa.Column("pdf_path", sa.String(512), nullable=True),
    )

    # ── applications ──────────────────────────────────────────────────────────
    op.create_table(
        "applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("status", sa.String(32), default="queued"),
        sa.Column("cover_letter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cover_letters.id"), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("platform_application_id", sa.String(256), nullable=True),
        sa.Column("form_answers", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("error_log", sa.Text(), nullable=True),
    )
    op.create_index("ix_applications_status", "applications", ["status"])
    op.create_index("ix_applications_job_id", "applications", ["job_id"])

    # ── hr_contacts ───────────────────────────────────────────────────────────
    op.create_table(
        "hr_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("company", sa.String(256), nullable=False),
        sa.Column("full_name", sa.String(256), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("linkedin_url", sa.String(512), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("found_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── outreach_messages ─────────────────────────────────────────────────────
    op.create_table(
        "outreach_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hr_contacts.id"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(32), default="draft"),
    )


def downgrade() -> None:
    op.drop_table("outreach_messages")
    op.drop_table("hr_contacts")
    op.drop_table("applications")
    op.drop_table("cover_letters")
    op.drop_table("documents")
    op.drop_table("cv_profile")
    op.drop_table("jobs")

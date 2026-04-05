"""003 — Add job_skills_matrix and cover_letter_style tables

Revision ID: 003
Revises: 002
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── job_skills_matrix ─────────────────────────────────────────────────────
    op.create_table(
        "job_skills_matrix",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("required_skills", postgresql.JSON, nullable=True),
        sa.Column("missing_skills", postgresql.JSON, nullable=True),
        sa.Column("niche_keywords", postgresql.JSON, nullable=True),
        sa.Column("cv_sections_to_highlight", postgresql.JSON, nullable=True),
        sa.Column("projects_to_mention", postgresql.JSON, nullable=True),
        sa.Column("ats_score", sa.Float, nullable=True),
        sa.Column("ats_keywords_to_add", postgresql.JSON, nullable=True),
        sa.Column("interview_topics", postgresql.JSON, nullable=True),
        sa.Column("analysis_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_job_skills_matrix_job_id",
        "job_skills_matrix",
        ["job_id"],
    )

    # ── cover_letter_style ────────────────────────────────────────────────────
    op.create_table(
        "cover_letter_style",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("style_summary", sa.Text, nullable=True),
        sa.Column("tone_markers", postgresql.JSON, nullable=True),
        sa.Column("structure_pattern", postgresql.JSON, nullable=True),
        sa.Column("strengths_highlighted", postgresql.JSON, nullable=True),
        sa.Column("sample_openings", postgresql.JSON, nullable=True),
        sa.Column("sample_closings", postgresql.JSON, nullable=True),
        sa.Column("raw_analysis", postgresql.JSON, nullable=True),
        sa.Column("sample_count", sa.Float, nullable=True),
        sa.Column("source_files", postgresql.JSON, nullable=True),
        sa.Column("learned_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("cover_letter_style")
    op.drop_index("ix_job_skills_matrix_job_id", "job_skills_matrix")
    op.drop_table("job_skills_matrix")

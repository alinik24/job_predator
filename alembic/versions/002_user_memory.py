"""User memory, job feedback, skill gaps, search sessions

Revision ID: 002
Revises: 001
Create Date: 2026-03-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── user_memory ───────────────────────────────────────────────────────────
    # Single-row table (one per user session) — holds all user preferences
    # and confirmed skills across all search rounds.
    op.create_table(
        "user_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        # Skills the user confirmed they have (LLM missed them or underclaimed)
        # Format: {"Python": "confirmed", "Docker": "learning", "React": "no"}
        sa.Column("skill_claims", postgresql.JSONB(), server_default="{}"),
        # Job title / role preferences
        # Format: {"Data Engineer": "preferred", "DevOps": "avoid"}
        sa.Column("position_preferences", postgresql.JSONB(), server_default="{}"),
        # Company names to permanently skip
        sa.Column("company_blacklist", postgresql.JSONB(), server_default="[]"),
        # Industries to prefer or avoid
        # Format: {"Energy": "preferred", "Banking": "neutral", "Defense": "avoid"}
        sa.Column("industry_preferences", postgresql.JSONB(), server_default="{}"),
        # Location preferences
        # Format: {"Berlin": "preferred", "Munich": "ok", "remote": "required"}
        sa.Column("location_preferences", postgresql.JSONB(), server_default="{}"),
        # Salary floor
        sa.Column("min_salary", sa.Float(), nullable=True),
        # "required" | "preferred" | "flexible" | "no"
        sa.Column("remote_preference", sa.String(16), server_default="'flexible'"),
        # Free-text notes: "I prefer research roles, not pure dev", etc.
        sa.Column("notes", sa.Text(), nullable=True),
        # Embedding of "ideal job" — centroid of liked job embeddings (for similarity scoring)
        sa.Column("preference_embedding", sa.Text(), nullable=True),  # vector(384)
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.execute(
        "ALTER TABLE user_memory ALTER COLUMN preference_embedding "
        "TYPE vector(384) USING preference_embedding::vector(384)"
    )

    # ── job_feedback ──────────────────────────────────────────────────────────
    # User's explicit decision on each job — the core RLHF signal.
    op.create_table(
        "job_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        # Decision made by user:
        #   interested / apply / skip / not_interested /
        #   applied_manually / got_interview / got_offer / rejected_by_company
        sa.Column("decision", sa.String(32), nullable=False),
        # User's own score estimate (overrides LLM score in future rounds)
        sa.Column("user_score", sa.Float(), nullable=True),
        # Free-text reason ("Too junior", "Good culture fit", "Missing Spark", …)
        sa.Column("reason", sa.Text(), nullable=True),
        # Snapshot of job embedding at feedback time — used to train preference model
        sa.Column("job_embedding_snapshot", sa.Text(), nullable=True),  # vector(384)
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.execute(
        "ALTER TABLE job_feedback ALTER COLUMN job_embedding_snapshot "
        "TYPE vector(384) USING job_embedding_snapshot::vector(384)"
    )
    op.create_index("ix_job_feedback_job_id", "job_feedback", ["job_id"])
    op.create_index("ix_job_feedback_decision", "job_feedback", ["decision"])

    # ── skill_gaps ────────────────────────────────────────────────────────────
    # Aggregated skill gaps across all scored jobs — shows what the market
    # asks for that the CV doesn't yet contain.
    op.create_table(
        "skill_gaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("skill_name", sa.String(256), nullable=False),
        # How many top jobs (score >= 7.0) required this skill
        sa.Column("frequency", sa.Integer(), server_default="1"),
        # Which job IDs mentioned this gap
        sa.Column("job_ids", postgresql.JSONB(), server_default="[]"),
        # User's claim about this skill:
        #   null = unreviewed | "have_it" | "learning" | "not_interested"
        sa.Column("user_claim", sa.String(32), nullable=True),
        # Suggested LaTeX snippet to add to Overleaf CV
        sa.Column("cv_suggestion", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("skill_name", name="uq_skill_gaps_name"),
    )
    op.create_index("ix_skill_gaps_frequency", "skill_gaps", ["frequency"])

    # ── search_sessions ───────────────────────────────────────────────────────
    # Records each search round — positions used, results, user-approved keywords.
    op.create_table(
        "search_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("positions_used", postgresql.JSONB(), nullable=False),
        sa.Column("positions_suggested", postgresql.JSONB(), server_default="[]"),
        sa.Column("positions_approved", postgresql.JSONB(), server_default="[]"),
        sa.Column("sources", postgresql.JSONB(), server_default="[]"),
        sa.Column("jobs_found", sa.Integer(), server_default="0"),
        sa.Column("jobs_scored", sa.Integer(), server_default="0"),
        sa.Column("jobs_above_threshold", sa.Integer(), server_default="0"),
        sa.Column("top_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("search_sessions")
    op.drop_table("skill_gaps")
    op.drop_table("job_feedback")
    op.drop_table("user_memory")

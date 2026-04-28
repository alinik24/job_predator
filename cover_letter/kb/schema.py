"""Database schema for intelligent cover letter knowledge base."""
from datetime import datetime, UTC

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, Text

from core.database import Base


class CoverLetterKnowledge(Base):
    """
    Knowledge base entry for each cover letter application.

    Stores full content + embeddings + structured metadata for:
    - Semantic similarity search (via embeddings)
    - Metadata filtering (category, institution, outcome)
    - Pattern learning (what worked for similar applications)
    """

    __tablename__ = "cover_letter_knowledge"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Full content
    cover_letter_text = Column(Text, nullable=False)
    job_description = Column(Text, nullable=False)
    cv_snapshot = Column(JSON, nullable=False)  # CV state at application time

    # Embeddings for semantic search (1536 dimensions for text-embedding-3-small)
    letter_embedding = Column(Vector(1536))
    job_embedding = Column(Vector(1536))

    # Structured metadata
    category = Column(String(100), nullable=False, index=True)
    institution_name = Column(String(500))
    institution_type = Column(String(100), index=True)  # University, Research Institute, Industry
    position_title = Column(String(500))

    # What was selected from CV (for pattern learning)
    projects_used = Column(JSON)  # [{"name": "...", "reason": "..."}]
    skills_emphasized = Column(JSON)  # {"primary": [...], "secondary": [...]}
    experience_highlighted = Column(JSON)
    research_interests_used = Column(JSON)  # [...]

    # Application outcome (for learning what works)
    outcome = Column(String(50), index=True)  # Pending, Interview, Offer, Rejected
    outcome_notes = Column(Text)

    # Pattern metadata
    tone_style = Column(String(100))
    special_paragraphs = Column(JSON)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # File metadata
    pdf_filename = Column(String(500))
    file_path = Column(String(1000))

    # Indexes for fast retrieval (PostgreSQL-specific, will be ignored by SQLite)
    # NOTE: Create ivfflat indexes AFTER initial data load with: lists = rows / 1000
    # __table_args__ = (
    #     Index(
    #         "idx_letter_embedding",
    #         "letter_embedding",
    #         postgresql_using="ivfflat",
    #         postgresql_with={"lists": 100},
    #         postgresql_ops={"letter_embedding": "vector_cosine_ops"},
    #     ),
    #     Index(
    #         "idx_job_embedding",
    #         "job_embedding",
    #         postgresql_using="ivfflat",
    #         postgresql_with={"lists": 100},
    #         postgresql_ops={"job_embedding": "vector_cosine_ops"},
    #     ),
    # )

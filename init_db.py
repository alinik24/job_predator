"""Initialize database with all tables."""
import asyncio
from sqlalchemy import text
from core.database import engine, Base
from core.models import (
    Job, CVProfile, UserProfile, Document, Application,
    CoverLetter, HRContact, OutreachMessage, UserMemory,
    JobFeedback, SkillGap, SearchSession, JobSkillsMatrix
)
from cover_letter.kb.schema import CoverLetterKnowledge

async def init_database():
    """Create all tables."""
    async with engine.begin() as conn:
        # Enable pgvector extension first
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Create all tables (both core and KB use the same Base)
        await conn.run_sync(Base.metadata.create_all)

    print("[OK] All tables created successfully")

if __name__ == "__main__":
    asyncio.run(init_database())

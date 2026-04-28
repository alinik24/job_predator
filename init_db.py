"""Initialize database with all tables."""
import asyncio
from core.database import engine, Base
from core.models import (
    Job, CVProfile, UserProfile, Document, Application,
    CoverLetter, HRContact, OutreachMessage, UserMemory,
    JobFeedback, SkillGap, SearchSession, JobSkillsMatrix
)

async def init_database():
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[OK] All tables created successfully")

if __name__ == "__main__":
    asyncio.run(init_database())

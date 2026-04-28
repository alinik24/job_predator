"""Tests for cover letter knowledge base schema."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from cover_letter.kb.schema import Base, CoverLetterKnowledge


@pytest_asyncio.fixture
async def test_db():
    """Create test database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_cover_letter_knowledge_creation(test_db):
    """Test creating a cover letter knowledge entry."""
    kb_entry = CoverLetterKnowledge(
        cover_letter_text="Sample cover letter text",
        job_description="Sample job description",
        cv_snapshot={"projects": [], "skills": []},
        category="AI/ML",
        institution_name="Test University",
        institution_type="University",
        position_title="Research Assistant",
        projects_used=[{"name": "Project A", "reason": "relevant"}],
        skills_emphasized={"primary": ["Python"], "secondary": ["SQL"]},
        outcome="Pending",
    )

    test_db.add(kb_entry)
    await test_db.commit()
    await test_db.refresh(kb_entry)

    assert kb_entry.id is not None
    assert kb_entry.category == "AI/ML"
    assert kb_entry.created_at is not None
    assert kb_entry.institution_name == "Test University"
    assert kb_entry.outcome == "Pending"

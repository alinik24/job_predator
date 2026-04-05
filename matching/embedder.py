"""
Embedding engine using sentence-transformers + pgvector.

Generates 384-dim embeddings for jobs and CV profile.
Stores embeddings in PostgreSQL via pgvector.
Provides semantic similarity search: find top-N similar jobs to a CV.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple
from uuid import UUID

import numpy as np
from loguru import logger
from sqlalchemy import select, text

from core.config import settings
from core.database import get_session
from core.models import CVProfile, Job

_model = None


def get_model():
    """Lazy-load the sentence-transformer model (cached after first call)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"[Embedder] Loading model: {settings.embedding_model}")
        _model = SentenceTransformer(settings.embedding_model)
        logger.info("[Embedder] Model loaded")
    return _model


def embed_text(text: str) -> List[float]:
    """Generate a single embedding vector for a text string."""
    model = get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a batch of texts."""
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=True)
    return vectors.tolist()


def text_for_job_embedding(job: Job) -> str:
    """Compose a representative text string for embedding a job posting."""
    parts = [
        job.title or "",
        job.company or "",
        job.location or "",
        job.description or "",
        job.requirements or "",
    ]
    return " ".join(filter(None, parts))[:2000]


def text_for_cv_embedding(profile: CVProfile) -> str:
    """Compose a representative text string for embedding a CV profile."""
    skills = " ".join(profile.skills or [])
    exp_parts = []
    for exp in (profile.work_experience or [])[:3]:
        if isinstance(exp, dict):
            exp_parts.append(
                f"{exp.get('title', '')} {exp.get('company', '')} "
                f"{exp.get('description', '')}"
            )
    return " ".join(filter(None, [
        profile.summary or "",
        skills,
        *exp_parts,
        profile.raw_text[:500] if profile.raw_text else "",
    ]))[:2000]


async def embed_and_store_job(job_id: UUID) -> None:
    """Generate and store embedding for a single job."""
    async with get_session() as session:
        job = await session.get(Job, job_id)
        if not job:
            return
        text = text_for_job_embedding(job)
        vector = embed_text(text)
        job.embedding = vector
        session.add(job)


async def embed_and_store_all_jobs(batch_size: int = 50) -> int:
    """Embed all jobs that don't have an embedding yet. Returns count processed."""
    async with get_session() as session:
        result = await session.execute(
            select(Job).where(Job.embedding.is_(None)).limit(500)
        )
        jobs = list(result.scalars().all())

    if not jobs:
        logger.info("[Embedder] All jobs already embedded")
        return 0

    logger.info(f"[Embedder] Embedding {len(jobs)} jobs...")
    texts = [text_for_job_embedding(j) for j in jobs]

    loop = asyncio.get_event_loop()
    vectors = await loop.run_in_executor(None, lambda: embed_batch(texts))

    async with get_session() as session:
        for job, vector in zip(jobs, vectors):
            job.embedding = vector
            session.add(job)

    logger.info(f"[Embedder] Stored {len(jobs)} job embeddings")
    return len(jobs)


async def embed_and_store_cv(profile_id: UUID) -> None:
    """Generate and store embedding for a CV profile."""
    async with get_session() as session:
        profile = await session.get(CVProfile, profile_id)
        if not profile:
            return
        text = text_for_cv_embedding(profile)
        loop = asyncio.get_event_loop()
        vector = await loop.run_in_executor(None, lambda: embed_text(text))
        profile.embedding = vector
        session.add(profile)


async def find_similar_jobs(
    cv_profile: CVProfile,
    top_k: int = 50,
    min_score: float = 0.3,
) -> List[Tuple[Job, float]]:
    """
    Find the top-K most similar jobs to a CV profile using pgvector cosine similarity.

    Returns list of (Job, similarity_score) tuples, sorted descending.
    """
    if cv_profile.embedding is None:
        await embed_and_store_cv(cv_profile.id)
        async with get_session() as session:
            cv_profile = await session.get(CVProfile, cv_profile.id)

    if cv_profile.embedding is None:
        logger.error("[Embedder] Could not generate CV embedding")
        return []

    # pgvector cosine similarity: 1 - (embedding <=> query_vector)
    embedding_str = "[" + ",".join(str(v) for v in cv_profile.embedding) + "]"

    async with get_session() as session:
        result = await session.execute(
            text(
                f"""
                SELECT id, 1 - (embedding <=> :embedding::vector) AS similarity
                FROM jobs
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
                """
            ),
            {"embedding": embedding_str, "top_k": top_k},
        )
        rows = result.fetchall()

    if not rows:
        return []

    # Fetch the actual Job objects
    job_ids = [row[0] for row in rows]
    similarity_map = {row[0]: row[1] for row in rows}

    async with get_session() as session:
        result = await session.execute(select(Job).where(Job.id.in_(job_ids)))
        jobs = {j.id: j for j in result.scalars().all()}

    results = []
    for job_id in job_ids:
        if job_id in jobs:
            similarity = similarity_map[job_id]
            if similarity >= min_score:
                results.append((jobs[job_id], float(similarity)))

    return sorted(results, key=lambda x: x[1], reverse=True)

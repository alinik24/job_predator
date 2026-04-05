"""
Hybrid job-CV matching scorer: Semantic Knowledge Graph + LLM.

Combines:
  1. Domain knowledge graph for semantic understanding (wind engineer → energy)
  2. Azure OpenAI for contextual evaluation
  3. Embedding similarity for efficient pre-filtering

This enables context-aware matching beyond simple keyword matching.
"""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

from loguru import logger
from openai import AzureOpenAI
from sqlalchemy import select

from core.config import settings, get_token_kwargs
from core.database import get_session
from core.models import ApplicationStatus, CVProfile, CVProfileSchema, Job
from cv.cv_parser import CVParser
from matching.semantic_enhancer import SemanticEnhancer

SCORING_PROMPT = """\
You are an expert recruiter and career advisor. Evaluate how well the candidate's profile matches the job posting.

Provide your evaluation as a JSON object with this exact schema:
{
  "score": <float 0-10>,
  "recommendation": <"strong apply" | "apply" | "maybe" | "skip">,
  "match_strengths": ["list of specific matching skills/experience"],
  "gaps": ["list of specific gaps or missing requirements"],
  "cover_letter_angle": "the strongest angle to take in the cover letter for this job",
  "key_keywords": ["important keywords from the job to include in application"]
}

Scoring guide:
  9-10: Perfect match — candidate clearly exceeds requirements
  7-8:  Strong match — most requirements met, apply with confidence
  5-6:  Moderate match — some gaps but worth applying with tailored materials
  3-4:  Weak match — significant gaps; only apply if position is highly desired
  0-2:  Poor match — fundamental misalignment, skip unless desperate

Be specific and precise. Do not be overly generous.
"""


class JobScorer:
    """Hybrid scorer: Semantic knowledge graph + LLM for contextual matching."""

    def __init__(self, cv_profile: CVProfileSchema, use_semantic: bool = True):
        self.cv_profile = cv_profile
        self.use_semantic = use_semantic
        self.client = AzureOpenAI(
            azure_endpoint=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            api_version=settings.llm_api_version,
        )
        self.model_name = settings.llm_model_name
        self._cv_summary = CVParser().get_cv_summary_for_llm(cv_profile)

        # Initialize semantic enhancer for knowledge graph matching
        if use_semantic:
            try:
                self.semantic_enhancer = SemanticEnhancer()
                logger.info("Semantic enhancer initialized for context-aware matching")
            except Exception as e:
                logger.warning(f"Could not initialize semantic enhancer: {e}")
                self.use_semantic = False

    def score_job(self, job: Job) -> dict:
        """
        Score a single job using hybrid approach:
        1. Semantic knowledge graph for context understanding
        2. LLM for detailed evaluation

        Returns the scoring dict with score, recommendation, strengths, gaps.
        """
        job_text = self._format_job_for_prompt(job)
        cv_text = self._cv_summary

        # Step 1: Semantic pre-scoring (fast, contextual)
        semantic_result = None
        if self.use_semantic and self.semantic_enhancer:
            try:
                cv_skills = self._extract_cv_skills()
                semantic_result = self.semantic_enhancer.semantic_match_score(
                    cv_skills,
                    job.description or job.title
                )
                logger.debug(f"Semantic pre-score: {semantic_result['score']}/10")
            except Exception as e:
                logger.warning(f"Semantic scoring failed: {e}")

        # Step 2: LLM scoring (slower, comprehensive)
        try:
            # Enhance prompt with semantic insights if available
            enhanced_prompt = SCORING_PROMPT
            if semantic_result:
                semantic_context = (
                    f"\n\nSemantic Analysis (Knowledge Graph):\n"
                    f"- Matched skills: {', '.join(semantic_result['matched_skills'][:5])}\n"
                    f"- Semantic relationships found: {len(semantic_result['semantic_matches'])}\n"
                    f"- Job domains: {', '.join(semantic_result['job_domains'][:3])}\n"
                    f"- Pre-score: {semantic_result['score']}/10\n"
                )
                enhanced_prompt += semantic_context

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": enhanced_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"JOB POSTING:\n{job_text}\n\n"
                            f"CANDIDATE PROFILE:\n{cv_text}"
                        ),
                    },
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                **get_token_kwargs(self.model_name, 1024),
            )

            result = json.loads(response.choices[0].message.content)
            llm_score = float(result.get("score", 0))

            # Hybrid score: combine semantic + LLM (weighted average)
            if semantic_result:
                final_score = (llm_score * 0.7) + (semantic_result['score'] * 0.3)
                result["semantic_boost"] = semantic_result['score']
                result["semantic_matches"] = [
                    f"{cv_skill} ↔ {job_req} ({sim:.2f})"
                    for cv_skill, job_req, sim in semantic_result['semantic_matches'][:3]
                ]
            else:
                final_score = llm_score

            result["score"] = round(final_score, 2)
            result["llm_score"] = llm_score
            return result

        except Exception as e:
            logger.error(f"[Scorer] Error scoring job {job.id}: {e}")
            return {"score": 0.0, "recommendation": "skip", "match_strengths": [], "gaps": [str(e)]}

    def _extract_cv_skills(self) -> List[str]:
        """Extract skill list from CV profile"""
        skills = []

        # Technical skills
        if hasattr(self.cv_profile, 'skills') and self.cv_profile.skills:
            if isinstance(self.cv_profile.skills, dict):
                for category, skill_list in self.cv_profile.skills.items():
                    if isinstance(skill_list, list):
                        skills.extend(skill_list)
            elif isinstance(self.cv_profile.skills, list):
                skills.extend(self.cv_profile.skills)

        # Education (as domain knowledge)
        if hasattr(self.cv_profile, 'education') and self.cv_profile.education:
            for edu in self.cv_profile.education:
                if isinstance(edu, dict):
                    if 'degree' in edu:
                        skills.append(edu['degree'])
                    if 'field' in edu:
                        skills.append(edu['field'])

        return skills

    async def score_and_update_job(self, job: Job) -> float:
        """Score a job and persist the score + reasons to DB."""
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: self.score_job(job))

        score = result.get("score", 0.0)
        async with get_session() as session:
            db_job = await session.get(Job, job.id)
            if db_job:
                db_job.match_score = score
                db_job.match_reasons = {
                    "recommendation": result.get("recommendation"),
                    "strengths": result.get("match_strengths", []),
                    "gaps": result.get("gaps", []),
                    "cover_letter_angle": result.get("cover_letter_angle", ""),
                    "key_keywords": result.get("key_keywords", []),
                }
                if score >= settings.auto_apply_threshold:
                    db_job.status = ApplicationStatus.QUEUED
                else:
                    db_job.status = ApplicationStatus.SKIPPED
                session.add(db_job)

        return score

    async def score_batch(self, jobs: List[Job]) -> List[Tuple[Job, float]]:
        """Score a batch of jobs. Returns sorted list of (job, score)."""
        import asyncio

        logger.info(f"[Scorer] Scoring {len(jobs)} jobs...")
        results = []

        for i, job in enumerate(jobs):
            score = await self.score_and_update_job(job)
            results.append((job, score))
            logger.info(
                f"[Scorer] [{i+1}/{len(jobs)}] '{job.title}' @ '{job.company}' "
                f"→ score={score:.1f}"
            )
            # Small delay to avoid Azure OpenAI rate limits
            if (i + 1) % 10 == 0:
                await asyncio.sleep(2)

        return sorted(results, key=lambda x: x[1], reverse=True)

    def _format_job_for_prompt(self, job: Job) -> str:
        parts = [
            f"Title: {job.title}",
            f"Company: {job.company}",
            f"Location: {job.location or 'Not specified'}",
            f"Remote: {'Yes' if job.is_remote else 'No'}",
        ]
        if job.salary_min or job.salary_max:
            parts.append(
                f"Salary: {job.salary_min or '?'} - {job.salary_max or '?'} {job.salary_currency}"
            )
        if job.description:
            parts.append(f"\nDescription:\n{job.description[:2000]}")

        return "\n".join(parts)


async def score_all_unscored_jobs(cv_profile: CVProfileSchema, batch_size: int = 50) -> int:
    """Score all jobs in DB that haven't been scored yet. Returns count scored."""
    from scrapers.aggregator import JobAggregator

    jobs = await JobAggregator.get_unscored_jobs(limit=batch_size)
    if not jobs:
        logger.info("[Scorer] No unscored jobs found")
        return 0

    scorer = JobScorer(cv_profile)
    results = await scorer.score_batch(jobs)
    above_threshold = sum(1 for _, score in results if score >= settings.auto_apply_threshold)

    logger.info(
        f"[Scorer] Scored {len(results)} jobs | "
        f"{above_threshold} above threshold ({settings.auto_apply_threshold})"
    )
    return len(results)

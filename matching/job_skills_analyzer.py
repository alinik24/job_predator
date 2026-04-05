"""
Per-Job Skills Analyzer
=======================
For each job, analyses the full job description and produces:

  1. Skills matrix: required skills + whether the user has each one
  2. Niche keywords: company/domain-specific terms to learn
  3. CV sections to emphasise for this specific job
  4. ATS score estimate (how well the CV matches the JD)
  5. Most relevant projects/experience to highlight

Results are stored in job_skills_matrix table and can be viewed per job.

Usage:
  python main.py analyze-job --job-id <uuid>
  python main.py analyze-job --all --min-score 7.0
"""
from __future__ import annotations

import json
from typing import List, Optional
from uuid import UUID

from loguru import logger
from core.llm_client import get_llm_client
from sqlalchemy import select

from core.config import settings, get_token_kwargs
from core.database import get_session
from core.models import CVProfileSchema, Job, JobSkillsMatrix
from cv.cv_parser import CVParser

SKILLS_ANALYSIS_PROMPT = """\
You are an expert technical recruiter and job market analyst.

Analyse the job posting and candidate profile below. Return a structured JSON object.

REQUIRED OUTPUT SCHEMA:
{
  "required_skills": [
    {
      "skill": "Python",
      "type": "must",
      "category": "tech",
      "user_has": true,
      "evidence": "extensive Python in CV/thesis",
      "importance": 5
    },
    ...
  ],
  "niche_keywords": [
    {
      "keyword": "Digital Twin of energy grid",
      "niche_context": "This company uses digital twins for grid simulation — specific tech area",
      "why_important": "Core to what this team does",
      "learn_resource": "IEEE paper on digital twins in power systems; ENTSO-E standards docs"
    },
    ...
  ],
  "cv_sections_to_highlight": [
    "Thesis: power system optimisation (directly relevant)",
    "Fraunhofer working student experience",
    "Python + pandas + ML skills section"
  ],
  "projects_to_mention": [
    "Master thesis — most relevant to core job requirements",
    "Fraunhofer project XYZ if present"
  ],
  "missing_skills": [
    {
      "skill": "Apache Kafka",
      "gap_severity": "minor",
      "workaround": "Can mention experience with similar event streaming via Python async"
    }
  ],
  "ats_score_estimate": 7.5,
  "ats_keywords_to_add": ["energy management system", "EMS", "SCADA"],
  "interview_topics_to_prepare": [
    "Questions about power flow algorithms",
    "Why this company and not a competitor"
  ],
  "overall_analysis": "2-3 sentence summary of fit and main angle to take"
}

IMPORTANT:
- user_has: true only if the evidence is in the CV summary. False = missing.
- niche_keywords: focus on company/domain-SPECIFIC terms, not generic skills
- importance: 1-5 where 5 = dealbreaker if missing
- ats_score_estimate: how well this CV would score in an ATS for this JD (0-10)

JOB POSTING:
{job_text}

CANDIDATE CV SUMMARY:
{cv_summary}
"""


class JobSkillsAnalyzer:
    """Analyses per-job skill requirements and produces skills matrix."""

    def __init__(self, cv_profile: CVProfileSchema):
        self.cv_profile = cv_profile
        llm_client = get_llm_client()
        self.client = llm_client.client
        self.model_name = llm_client.model_name
        self.model_name = settings.llm_model_name
        self._cv_summary = CVParser().get_cv_summary_for_llm(cv_profile, rich=True)

    async def analyze_job(self, job: Job) -> JobSkillsMatrix:
        """
        Analyse a job and return/persist its skills matrix.
        """
        import asyncio
        logger.info(f"[SkillsAnalyzer] Analysing '{job.title}' @ '{job.company}'")

        job_text = (
            f"Title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location or 'N/A'}\n"
            f"Description:\n{(job.description or '')[:3500]}"
        )

        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(None, lambda: self._call_llm(job_text))

        return await self._upsert_matrix(job, analysis)

    def _call_llm(self, job_text: str) -> dict:
        try:
            prompt = SKILLS_ANALYSIS_PROMPT.format(
                job_text=job_text,
                cv_summary=self._cv_summary[:2500],
            )
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are an expert technical recruiter. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                **get_token_kwargs(self.model_name, 2000),
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"[SkillsAnalyzer] LLM error: {e}")
            return {}

    async def _upsert_matrix(self, job: Job, analysis: dict) -> JobSkillsMatrix:
        async with get_session() as session:
            # Check if exists
            result = await session.execute(
                select(JobSkillsMatrix).where(JobSkillsMatrix.job_id == job.id)
            )
            matrix = result.scalar_one_or_none()

            if matrix:
                matrix.required_skills = analysis.get("required_skills", [])
                matrix.niche_keywords = analysis.get("niche_keywords", [])
                matrix.missing_skills = analysis.get("missing_skills", [])
                matrix.cv_sections_to_highlight = analysis.get("cv_sections_to_highlight", [])
                matrix.projects_to_mention = analysis.get("projects_to_mention", [])
                matrix.ats_score = analysis.get("ats_score_estimate")
                matrix.ats_keywords_to_add = analysis.get("ats_keywords_to_add", [])
                matrix.interview_topics = analysis.get("interview_topics_to_prepare", [])
                matrix.analysis_summary = analysis.get("overall_analysis", "")
            else:
                matrix = JobSkillsMatrix(
                    job_id=job.id,
                    required_skills=analysis.get("required_skills", []),
                    niche_keywords=analysis.get("niche_keywords", []),
                    missing_skills=analysis.get("missing_skills", []),
                    cv_sections_to_highlight=analysis.get("cv_sections_to_highlight", []),
                    projects_to_mention=analysis.get("projects_to_mention", []),
                    ats_score=analysis.get("ats_score_estimate"),
                    ats_keywords_to_add=analysis.get("ats_keywords_to_add", []),
                    interview_topics=analysis.get("interview_topics_to_prepare", []),
                    analysis_summary=analysis.get("overall_analysis", ""),
                )
                session.add(matrix)

            await session.flush()
            await session.refresh(matrix)

        logger.info(
            f"[SkillsAnalyzer] Matrix saved | ATS: {matrix.ats_score or 'N/A'} | "
            f"Skills: {len(matrix.required_skills or [])} | "
            f"Niche keywords: {len(matrix.niche_keywords or [])}"
        )
        return matrix

    async def analyze_batch(
        self, jobs: List[Job], concurrency: int = 3
    ) -> List[JobSkillsMatrix]:
        """Analyse multiple jobs with limited concurrency."""
        import asyncio
        sem = asyncio.Semaphore(concurrency)

        async def _bounded(job):
            async with sem:
                try:
                    return await self.analyze_job(job)
                except Exception as e:
                    logger.error(f"[SkillsAnalyzer] Failed for {job.id}: {e}")
                    return None

        results = await asyncio.gather(*[_bounded(j) for j in jobs])
        return [r for r in results if r is not None]

    @staticmethod
    async def get_matrix(job_id) -> Optional[JobSkillsMatrix]:
        async with get_session() as session:
            result = await session.execute(
                select(JobSkillsMatrix).where(JobSkillsMatrix.job_id == job_id)
            )
            return result.scalar_one_or_none()

    @staticmethod
    def format_skills_report(matrix: JobSkillsMatrix, job: Job) -> str:
        """Format a skills matrix into a readable report."""
        lines = [
            f"{'='*65}",
            f"SKILLS ANALYSIS: {job.title} @ {job.company}",
            f"{'='*65}",
        ]

        if matrix.ats_score:
            lines.append(f"\nATS Match Score: {matrix.ats_score:.1f}/10")
        if matrix.analysis_summary:
            lines.append(f"\nSummary: {matrix.analysis_summary}")

        # Skills matrix
        skills = matrix.required_skills or []
        if skills:
            have = [s for s in skills if s.get("user_has")]
            missing = [s for s in skills if not s.get("user_has")]

            if have:
                lines.append(f"\n✓ YOU HAVE ({len(have)} skills):")
                for s in sorted(have, key=lambda x: -x.get("importance", 0)):
                    imp = "★" * s.get("importance", 1)
                    lines.append(f"   {imp} {s['skill']} [{s.get('category', '')}] — {s.get('evidence', '')[:80]}")

            if missing:
                lines.append(f"\n✗ MISSING ({len(missing)} skills):")
                for s in sorted(missing, key=lambda x: -x.get("importance", 0)):
                    imp = "★" * s.get("importance", 1)
                    lines.append(f"   {imp} {s['skill']} [{s.get('type', '')} / {s.get('category', '')}]")

        # Missing with workarounds
        missing_detailed = matrix.missing_skills or []
        if missing_detailed:
            lines.append("\nGAP WORKAROUNDS:")
            for g in missing_detailed:
                lines.append(f"   • {g.get('skill', '')}: {g.get('workaround', '')}")

        # CV sections to highlight
        if matrix.cv_sections_to_highlight:
            lines.append("\nEMPHASISE IN APPLICATION:")
            for s in matrix.cv_sections_to_highlight[:4]:
                lines.append(f"   → {s}")

        # Projects to mention
        if matrix.projects_to_mention:
            lines.append("\nMENTION THESE PROJECTS:")
            for p in matrix.projects_to_mention[:3]:
                lines.append(f"   • {p}")

        # Niche keywords
        niche = matrix.niche_keywords or []
        if niche:
            lines.append(f"\nNICHE KEYWORDS TO LEARN ({len(niche)}):")
            for kw in niche[:5]:
                lines.append(f"   [{kw.get('keyword', '')}]")
                lines.append(f"     Why: {kw.get('why_important', '')}")
                lines.append(f"     Context: {kw.get('niche_context', '')}")
                if kw.get("learn_resource"):
                    lines.append(f"     Learn: {kw['learn_resource']}")

        # ATS keywords to add
        if matrix.ats_keywords_to_add:
            lines.append(f"\nATS KEYWORDS TO ADD TO CV/LETTER:")
            lines.append(f"   {', '.join(matrix.ats_keywords_to_add[:8])}")

        # Interview prep
        if matrix.interview_topics:
            lines.append("\nPREPARE FOR INTERVIEW:")
            for t in matrix.interview_topics[:4]:
                lines.append(f"   • {t}")

        lines.append(f"\n{'='*65}")
        lines.append(f"Generate cover letter: python main.py cover-letter --job-id {job.id}")
        return "\n".join(lines)

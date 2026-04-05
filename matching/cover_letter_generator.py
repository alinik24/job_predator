"""
Cover Letter Generator
======================
Generates a fully tailored cover letter for a specific job by combining:

  1. Full CV profile (all fields: education, projects, thesis, experience)
  2. User's personal profile context (motivation, goals, extra context)
  3. Job requirements (deeply parsed: must-have, nice-to-have, implicit)
  4. Learned writing style (from existing cover letters via CoverLetterLearner)
  5. Job-specific skills matrix (which CV sections are most relevant)

Output:
  - Professional cover letter in the user's own style
  - In German or English depending on job posting language
  - With specific CV section / project recommendations highlighted
  - Saved to DB (CoverLetter table) + optionally to a .txt file

Usage:
  python main.py cover-letter --job-id <uuid>
  python main.py cover-letter --job-id <uuid> --lang de --output cover.txt
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from uuid import UUID

from loguru import logger
from openai import AzureOpenAI

from core.config import settings, get_token_kwargs
from core.database import get_session
from core.models import CoverLetter, CVProfileSchema, Job
from core.user_profile import UserProfileManager
from cv.cv_parser import CVParser


COVER_LETTER_PROMPT = """\
You are an expert career coach and native-level writer in both German and English.

Write a highly tailored, compelling cover letter for the job posting below.

═══════════════════════════════════════════════
STRICT REQUIREMENTS:
═══════════════════════════════════════════════
1. LENGTH: Exactly one page (350-450 words in the body). Never more.
2. FORMAT: Plain text. No markdown. No bullet points. Proper paragraphs.
3. LANGUAGE: {language_instruction}
4. PERSONALISATION: Every sentence must be specific to THIS job and THIS candidate.
   Zero generic phrases. Zero filler.
5. STRUCTURE:
   - Opening (1 paragraph): Hook with specific connection to THIS company/role.
     Show you know what they do. Why THIS company, not just any company.
   - Body (2-3 paragraphs): Map the 2-3 strongest CV highlights to the job's
     top requirements. Use the MOST RELEVANT experience, project, or education.
     Include at least one specific achievement with context.
   - Closing (1 paragraph): What you will contribute. Clear call to action.
6. TONE: {tone_instruction}
7. DO NOT include: the date, address blocks, "Dear Sir/Madam", "Sincerely" —
   just write the letter body from the opening salutation onward.

═══════════════════════════════════════════════
CANDIDATE INFORMATION:
═══════════════════════════════════════════════
{cv_summary}

{user_profile_context}

{style_guidance}

═══════════════════════════════════════════════
JOB POSTING ANALYSIS:
═══════════════════════════════════════════════
{job_analysis}

═══════════════════════════════════════════════
TAILORING INSTRUCTIONS (most relevant matches):
═══════════════════════════════════════════════
{tailoring_notes}

Write the cover letter now. Start directly with the salutation (e.g. "Sehr geehrte Damen und Herren," or "Dear Hiring Team,").
"""

JOB_ANALYSIS_PROMPT = """\
You are an expert job requirements analyst.

Analyse this job posting and return a JSON object with the following structure:

{
  "detected_language": "de" or "en",
  "company_name": "exact name",
  "role_summary": "1-sentence what this role actually does",
  "top_3_requirements": ["most critical requirement", "second", "third"],
  "must_have_skills": ["skill1", "skill2", ...],
  "nice_to_have_skills": ["skill1", ...],
  "implicit_requirements": ["inferred from context, not stated explicitly"],
  "company_mission_hint": "what the company is trying to achieve based on the posting",
  "cultural_cues": ["remote-first", "research-oriented", "fast-paced startup", etc.],
  "red_flags": ["any concerning elements: unclear role, unstable company, etc."],
  "cv_sections_to_emphasise": ["based on requirements, which CV sections are most relevant"],
  "killer_keywords": ["exact terms from the JD that must appear in the cover letter"],
  "tailoring_angle": "the single strongest angle to take in this cover letter"
}

JOB POSTING:
{job_text}
"""


class CoverLetterGenerator:
    """Generates tailored cover letters using CV, profile, style, and job analysis."""

    def __init__(self, cv_profile: CVProfileSchema):
        self.cv_profile = cv_profile
        self.client = AzureOpenAI(
            azure_endpoint=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            api_version=settings.llm_api_version,
        )
        self.model_name = settings.llm_model_name
        self._cv_parser = CVParser()
        self._profile_manager = UserProfileManager()

    async def generate_for_job(
        self,
        job: Job,
        language: Optional[str] = None,
        save_to_db: bool = True,
        output_file: Optional[Path] = None,
    ) -> str:
        """
        Generate a fully tailored cover letter for a job.
        Returns the cover letter text.
        """
        import asyncio

        logger.info(f"[CoverLetter] Generating for job: {job.title} @ {job.company}")

        # 1. Analyse the job posting
        loop = asyncio.get_event_loop()
        job_analysis = await loop.run_in_executor(None, lambda: self._analyse_job(job))

        # 2. Detect language if not specified
        if not language:
            language = job_analysis.get("detected_language", "de")

        # 3. Build CV summary (rich mode — all sections)
        cv_text = self._cv_parser.get_cv_summary_for_llm(self.cv_profile, rich=True)

        # 4. Get user profile context
        user_context = self._profile_manager.build_context_for_llm(
            job_description=job.description or ""
        )

        # 5. Get learned writing style
        style_guidance = ""
        try:
            from cv.cover_letter_learner import CoverLetterLearner
            style = await CoverLetterLearner.get_style()
            if style:
                style_guidance = CoverLetterLearner.format_style_for_prompt(style)
        except Exception:
            pass

        # 6. Build tailoring notes based on job analysis
        tailoring = self._build_tailoring_notes(job_analysis)

        # 7. Generate the cover letter
        letter = await loop.run_in_executor(
            None,
            lambda: self._generate_letter(
                cv_text=cv_text,
                user_context=user_context,
                style_guidance=style_guidance,
                job_analysis=job_analysis,
                tailoring=tailoring,
                language=language,
            )
        )

        # 8. Save to DB
        if save_to_db:
            await self._save_to_db(job, letter, language)

        # 9. Save to file
        if output_file:
            output_file = Path(output_file)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(letter, encoding="utf-8")
            logger.info(f"[CoverLetter] Saved to {output_file}")

        logger.info(f"[CoverLetter] Generated {len(letter)} chars cover letter")
        return letter

    def _analyse_job(self, job: Job) -> dict:
        """Analyse the job posting to extract structured requirements."""
        job_text = (
            f"Title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location or 'N/A'}\n"
            f"Description:\n{(job.description or '')[:3000]}"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are an expert job requirements analyst. Return only valid JSON."},
                    {"role": "user", "content": JOB_ANALYSIS_PROMPT.format(job_text=job_text)},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                **get_token_kwargs(self.model_name, 1500),
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.warning(f"[CoverLetter] Job analysis failed: {e}")
            return {
                "detected_language": "de",
                "company_name": job.company,
                "top_3_requirements": [],
                "must_have_skills": [],
                "tailoring_angle": "Highlight most relevant experience",
            }

    def _generate_letter(
        self,
        cv_text: str,
        user_context: str,
        style_guidance: str,
        job_analysis: dict,
        tailoring: str,
        language: str,
    ) -> str:
        lang_instruction = (
            "Write in GERMAN (Deutsch). Use formal Sie-form."
            if language == "de"
            else "Write in ENGLISH. Use professional but warm tone."
        )
        cl_prefs = self._profile_manager.get_cover_letter_preferences()
        tone_raw = cl_prefs.get("tone", "professional but warm")
        tone_instruction = f"{tone_raw}. Not overly formal. Authentic. Never generic."

        # Format job analysis as readable text
        job_analysis_text = (
            f"Role summary: {job_analysis.get('role_summary', '')}\n"
            f"Top 3 requirements: {'; '.join(job_analysis.get('top_3_requirements', []))}\n"
            f"Must-have skills: {', '.join(job_analysis.get('must_have_skills', [])[:8])}\n"
            f"Company mission: {job_analysis.get('company_mission_hint', '')}\n"
            f"Cultural cues: {', '.join(job_analysis.get('cultural_cues', []))}\n"
            f"Keywords to include: {', '.join(job_analysis.get('killer_keywords', [])[:6])}"
        )

        prompt = COVER_LETTER_PROMPT.format(
            language_instruction=lang_instruction,
            tone_instruction=tone_instruction,
            cv_summary=cv_text[:3000],
            user_profile_context=f"\nUSER PROFILE & PERSONAL CONTEXT:\n{user_context}" if user_context else "",
            style_guidance=f"\n{style_guidance}" if style_guidance else "",
            job_analysis=job_analysis_text,
            tailoring_notes=tailoring,
        )

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": "You are an expert cover letter writer. Write naturally, specifically, compellingly."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            **get_token_kwargs(self.model_name, 1200),
        )
        return response.choices[0].message.content.strip()

    def _build_tailoring_notes(self, analysis: dict) -> str:
        """Build human-readable tailoring notes from job analysis."""
        lines = []
        angle = analysis.get("tailoring_angle", "")
        if angle:
            lines.append(f"Primary angle: {angle}")
        sections = analysis.get("cv_sections_to_emphasise", [])
        if sections:
            lines.append(f"Emphasise these CV sections: {'; '.join(sections[:4])}")
        implicit = analysis.get("implicit_requirements", [])
        if implicit:
            lines.append(f"Address implicitly: {'; '.join(implicit[:3])}")
        red_flags = analysis.get("red_flags", [])
        if red_flags:
            lines.append(f"Note (but don't mention directly): {'; '.join(red_flags[:2])}")
        return "\n".join(lines)

    async def _save_to_db(self, job: Job, content: str, language: str) -> None:
        """Save generated cover letter to DB."""
        async with get_session() as session:
            cl = CoverLetter(
                job_id=job.id,
                content=content,
                language=language,
            )
            session.add(cl)
        logger.info(f"[CoverLetter] Saved to DB for job {job.id}")

    @staticmethod
    async def get_for_job(job_id) -> Optional[CoverLetter]:
        """Load the latest cover letter for a job."""
        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(CoverLetter)
                .where(CoverLetter.job_id == job_id)
                .order_by(CoverLetter.generated_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

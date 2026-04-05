"""
Cover letter generator — creates tailored cover letters per job using Azure OpenAI.

The generator:
  1. Reads your master CV profile
  2. Analyzes the job description to find the best matching angle
  3. Generates a professional cover letter in German or English
  4. Saves to database and exports to DOCX/PDF
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from uuid import UUID

from loguru import logger
from openai import AzureOpenAI
from sqlalchemy import select

from core.config import settings, get_token_kwargs
from core.database import get_session
from core.models import CoverLetter, CVProfileSchema, Job

GERMAN_COVER_LETTER_PROMPT = """\
Du bist ein professioneller Karriereberater und Bewerbungsschreiben-Experte.
Verfasse ein überzeugendes Anschreiben auf Deutsch für die folgende Stelle.

ANWEISUNGEN:
- Schreibe in einem professionellen, aber persönlichen Ton
- Verwende spezifische Details aus der Stellenanzeige und dem Lebenslauf
- Hebe die relevantesten Erfahrungen und Fähigkeiten hervor
- Gehe auf den angegebenen "Bewerbungswinkel" ein
- Länge: 3-4 Absätze (nicht mehr als 400 Wörter)
- Kein "Sehr geehrte Damen und Herren" — nutze den Kontaktnamen wenn bekannt
- Beende mit einer konkreten Aufforderung zum Handeln (Interview-Wunsch)
- Füge KEINE Kontaktdaten, Datum oder Betreffzeile hinzu — nur den Fließtext

BEWERBER-PROFIL:
{cv_summary}

STELLENANZEIGE:
Unternehmen: {company}
Position: {title}
Standort: {location}
Beschreibung: {description}

BEWERBUNGSWINKEL (betone diese Aspekte):
{angle}

SCHLÜSSELWÖRTER aus der Anzeige (füge relevante organisch ein):
{keywords}
"""

ENGLISH_COVER_LETTER_PROMPT = """\
You are a professional career advisor and expert cover letter writer.
Write a compelling cover letter in English for the following position.

INSTRUCTIONS:
- Professional but personable tone
- Use specific details from both the job description and the CV
- Highlight the most relevant experience and skills
- Address the specified "application angle"
- Length: 3-4 paragraphs (max 400 words)
- If the hiring manager's name is unknown, use "Dear Hiring Team" or "Dear [Company] Team"
- End with a concrete call to action (request for interview)
- Do NOT include contact details, date, or subject line — just the body text

CANDIDATE PROFILE:
{cv_summary}

JOB POSTING:
Company: {company}
Position: {title}
Location: {location}
Description: {description}

APPLICATION ANGLE (emphasize these):
{angle}

KEY KEYWORDS from posting (include relevant ones naturally):
{keywords}
"""


class CoverLetterGenerator:
    """Generates tailored cover letters using Azure OpenAI."""

    def __init__(self, cv_profile: CVProfileSchema):
        self.cv_profile = cv_profile
        self.client = AzureOpenAI(
            azure_endpoint=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            api_version=settings.llm_api_version,
        )
        self.model_name = settings.llm_model_name
        from cv.cv_parser import CVParser
        self._cv_summary = CVParser().get_cv_summary_for_llm(cv_profile)

    def generate(
        self,
        job: Job,
        language: str = "de",
        angle: Optional[str] = None,
        keywords: Optional[list] = None,
    ) -> str:
        """
        Generate a cover letter for a specific job.

        Args:
            job: The job to apply for
            language: "de" for German, "en" for English
            angle: The recommended angle from the job scorer (match_reasons)
            keywords: Key words from the job to include

        Returns:
            Cover letter text (body only, no headers)
        """
        # Get angle from match_reasons if not provided
        if not angle and job.match_reasons:
            reasons = job.match_reasons
            if isinstance(reasons, dict):
                angle = reasons.get("cover_letter_angle", "")
                if not keywords:
                    keywords = reasons.get("key_keywords", [])

        angle = angle or "Highlight your most relevant skills and enthusiasm for the role"
        keywords = keywords or []

        prompt_template = (
            GERMAN_COVER_LETTER_PROMPT if language == "de" else ENGLISH_COVER_LETTER_PROMPT
        )

        prompt = prompt_template.format(
            cv_summary=self._cv_summary,
            company=job.company,
            title=job.title,
            location=job.location or "Germany",
            description=(job.description or "")[:2000],
            angle=angle,
            keywords=", ".join(keywords[:20]),
        )

        logger.info(
            f"[CoverLetter] Generating for '{job.title}' @ '{job.company}' (lang={language})"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are an expert cover letter writer."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                **get_token_kwargs(self.model_name, 800),
            )
            text = response.choices[0].message.content.strip()
            logger.info(f"[CoverLetter] Generated {len(text)} chars")
            return text

        except Exception as e:
            logger.error(f"[CoverLetter] Generation error: {e}")
            raise

    async def generate_and_store(
        self,
        job: Job,
        language: str = "de",
        export_dir: Optional[str] = None,
    ) -> CoverLetter:
        """
        Generate a cover letter, store in DB, and export to DOCX + PDF.
        Returns the CoverLetter ORM object.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        content = await loop.run_in_executor(
            None, lambda: self.generate(job, language)
        )

        # Export to files
        export_dir = Path(export_dir or settings.output_dir)
        export_dir.mkdir(parents=True, exist_ok=True)

        safe_name = f"{job.company}_{job.title}".replace(" ", "_").replace("/", "-")[:60]
        docx_path = str(export_dir / f"cover_letter_{safe_name}.docx")
        pdf_path = str(export_dir / f"cover_letter_{safe_name}.pdf")

        try:
            from cover_letter.exporter import export_to_docx, export_to_pdf
            export_to_docx(content, docx_path, job, self.cv_profile)
            export_to_pdf(content, pdf_path, job, self.cv_profile)
        except Exception as e:
            logger.warning(f"[CoverLetter] Export error (continuing): {e}")
            docx_path = None
            pdf_path = None

        # Save to DB
        async with get_session() as session:
            cover = CoverLetter(
                job_id=job.id,
                content=content,
                language=language,
                docx_path=docx_path,
                pdf_path=pdf_path,
            )
            session.add(cover)
            await session.flush()
            await session.refresh(cover)

        logger.info(f"[CoverLetter] Stored cover letter id={cover.id}")
        return cover

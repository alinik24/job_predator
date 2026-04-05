"""
CV Parser — uses Azure OpenAI to extract structured data from CV text.

Input:  raw text from pdf_extractor or latex_extractor
Output: CVProfileSchema (structured JSON)

Also handles:
  - Storing the parsed profile in PostgreSQL
  - Generating a profile embedding for semantic matching
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from loguru import logger
from core.llm_client import get_llm_client

from core.config import settings, get_token_kwargs
from core.database import get_session
from core.models import CVProfile, CVProfileSchema
from cv.latex_extractor import (
    extract_structured_sections,
    extract_text_from_latex,
    find_overleaf_main_file,
)
from cv.pdf_extractor import extract_text_from_pdf


EXTRACTION_PROMPT = """\
You are an expert CV/resume parser. Extract all information from the following CV text into a JSON object.

IMPORTANT INSTRUCTIONS:
- Extract EVERY piece of information present; do not invent or assume
- For work experience, preserve exact dates, responsibilities, and achievements
- For skills, include ALL technical skills, tools, languages, frameworks mentioned
- For education, include institution, degree, field, dates, grades if present
- For languages, include proficiency levels (e.g. Native, C1, B2, Conversational)
- The CV may be in German or English — extract and output in English
- German-specific fields: "Lebenslauf" = CV, "Ausbildung" = education, "Berufserfahrung" = work experience

Return ONLY a valid JSON object with this exact schema:
{
  "full_name": "string",
  "email": "string or null",
  "phone": "string or null",
  "location": "string or null",
  "linkedin_url": "string or null",
  "github_url": "string or null",
  "summary": "string or null",
  "skills": ["list", "of", "skills"],
  "languages": [{"language": "string", "proficiency": "string"}],
  "work_experience": [
    {
      "title": "string",
      "company": "string",
      "location": "string or null",
      "start_date": "string",
      "end_date": "string or 'Present'",
      "description": "string",
      "achievements": ["list"]
    }
  ],
  "education": [
    {
      "degree": "string",
      "field": "string",
      "institution": "string",
      "location": "string or null",
      "start_date": "string",
      "end_date": "string",
      "grade": "string or null"
    }
  ],
  "certifications": ["list"],
  "publications": ["list"],
  "projects": [{"name": "string", "description": "string", "tech": ["list"]}]
}
"""


class CVParser:
    """Parses CV from PDF or LaTeX source using Azure OpenAI."""

    def __init__(self):
        llm_client = get_llm_client(); self.client = llm_client.client; self.model_name = llm_client.model_name
        self.model_name = settings.llm_model_name

    def extract_text(self, source: str | Path) -> str:
        """Auto-detect source type and extract text."""
        path = Path(source)

        if path.suffix.lower() == ".pdf":
            return extract_text_from_pdf(path)

        if path.suffix.lower() in (".tex", ".latex"):
            return extract_text_from_latex(path)

        if path.is_dir():
            # Assume Overleaf project directory
            main = find_overleaf_main_file(path)
            if main:
                logger.info(f"[CV] Found Overleaf main file: {main}")
                return extract_text_from_latex(main)
            raise ValueError(f"No .tex file found in directory: {path}")

        raise ValueError(f"Unsupported CV source: {path}")

    def parse(self, text: str) -> CVProfileSchema:
        """
        Parse raw CV text into structured CVProfileSchema using Azure OpenAI.
        """
        logger.info(f"[CV] Parsing CV text ({len(text)} chars)")

        # Truncate if too long for context window
        max_chars = 12000
        if len(text) > max_chars:
            logger.warning(f"[CV] Truncating text from {len(text)} to {max_chars} chars")
            text = text[:max_chars]

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": EXTRACTION_PROMPT},
                    {"role": "user", "content": f"CV TEXT:\n\n{text}"},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
                **get_token_kwargs(self.model_name, 4096),
            )

            raw_json = response.choices[0].message.content
            data = json.loads(raw_json)

            profile = CVProfileSchema(
                full_name=data.get("full_name"),
                email=data.get("email"),
                phone=data.get("phone"),
                location=data.get("location"),
                linkedin_url=data.get("linkedin_url"),
                github_url=data.get("github_url"),
                summary=data.get("summary"),
                skills=data.get("skills", []),
                languages=data.get("languages", []),
                work_experience=data.get("work_experience", []),
                education=data.get("education", []),
                certifications=data.get("certifications", []),
                raw_text=text,
            )

            logger.info(
                f"[CV] Parsed: {profile.full_name} | "
                f"{len(profile.skills)} skills | "
                f"{len(profile.work_experience)} jobs | "
                f"{len(profile.education)} degrees"
            )
            return profile

        except json.JSONDecodeError as e:
            logger.error(f"[CV] JSON decode error: {e}")
            raise
        except Exception as e:
            logger.error(f"[CV] Azure OpenAI error: {e}")
            raise

    async def parse_and_store(self, source: str | Path) -> CVProfile:
        """
        Full pipeline: extract text → parse with LLM → store in DB.
        Returns the persisted CVProfile ORM object.
        """
        text = self.extract_text(source)
        schema = self.parse(text)

        async with get_session() as session:
            profile = CVProfile(
                full_name=schema.full_name,
                email=schema.email,
                phone=schema.phone,
                location=schema.location,
                linkedin_url=schema.linkedin_url,
                github_url=schema.github_url,
                summary=schema.summary,
                skills=schema.skills,
                languages=schema.languages,
                work_experience=schema.work_experience,
                education=schema.education,
                certifications=schema.certifications,
                raw_text=schema.raw_text,
                source_file=str(source),
            )
            session.add(profile)
            await session.flush()
            await session.refresh(profile)

        logger.info(f"[CV] Profile stored in DB: id={profile.id}")
        return profile

    def get_cv_summary_for_llm(self, schema: CVProfileSchema, rich: bool = True) -> str:
        """
        Produce a text representation of the CV for use in LLM prompts.

        rich=True (default): includes ALL education details, achievements,
          certifications, languages — for scoring and gap analysis.
        rich=False: compact version for token-sensitive contexts.
        """
        parts = []

        if schema.full_name:
            parts.append(f"Name: {schema.full_name}")
        if schema.location:
            parts.append(f"Location: {schema.location}")
        if schema.summary:
            parts.append(f"\nSummary:\n{schema.summary}")

        # Skills — include all of them for rich mode
        if schema.skills:
            skill_limit = len(schema.skills) if rich else 30
            parts.append(f"\nSkills ({len(schema.skills)} total): "
                         f"{', '.join(schema.skills[:skill_limit])}")

        if schema.languages:
            lang_str = ", ".join(
                f"{l.get('language', '')} ({l.get('proficiency', '')})"
                for l in schema.languages
            )
            parts.append(f"Languages: {lang_str}")

        # Education — full details in rich mode (critical for research/energy roles)
        if schema.education:
            parts.append("\nEducation:")
            for edu in schema.education:
                grade = f", Grade: {edu.get('grade')}" if edu.get("grade") else ""
                thesis = f", Thesis: {edu.get('thesis', '')[:100]}" if edu.get("thesis") else ""
                parts.append(
                    f"  - {edu.get('degree')} in {edu.get('field')} "
                    f"at {edu.get('institution')} "
                    f"({edu.get('start_date', '')}–{edu.get('end_date', '')})"
                    f"{grade}{thesis}"
                )

        # Work experience — include achievements in rich mode
        if schema.work_experience:
            exp_limit = 7 if rich else 5
            parts.append("\nWork Experience:")
            for exp in schema.work_experience[:exp_limit]:
                start = exp.get("start_date", "")
                end = exp.get("end_date", "Present")
                parts.append(
                    f"  - {exp.get('title')} at {exp.get('company')} "
                    f"({start} – {end})"
                )
                desc = exp.get("description", "")
                if desc:
                    desc_limit = 400 if rich else 200
                    parts.append(f"    {desc[:desc_limit]}")
                if rich:
                    for ach in (exp.get("achievements") or [])[:3]:
                        parts.append(f"    • {str(ach)[:200]}")

        if schema.certifications:
            cert_limit = len(schema.certifications) if rich else 10
            parts.append(f"\nCertifications: {', '.join(schema.certifications[:cert_limit])}")

        # Publications / projects extracted from raw_text (rich mode)
        if rich and schema.raw_text:
            rt = schema.raw_text
            for section_kw in ["publication", "project", "award", "volunteer"]:
                idx = rt.lower().find(section_kw)
                if idx != -1:
                    snippet = rt[idx:idx + 500].strip()
                    parts.append(f"\n[{section_kw.capitalize()}s / Additional]:\n{snippet}")
                    break  # only include first extra section to keep within token budget

        return "\n".join(parts)

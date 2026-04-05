"""
Cover Letter Style Learner
==========================
Reads all PDFs from the user's cover letter folder, extracts text,
and uses the LLM to analyse writing style, structure, tone, and which
strengths the user typically emphasises.

The result is stored as a CoverLetterStyle row in the DB, and used by
CoverLetterGenerator to match the user's authentic writing style.

Workflow:
  python main.py learn-style --dir "C:/path/to/Cover Letters"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from loguru import logger
from openai import AzureOpenAI

from core.config import settings, get_token_kwargs
from core.database import get_session
from core.models import CoverLetterStyle
from cv.pdf_extractor import extract_text_from_pdf

STYLE_ANALYSIS_PROMPT = """\
You are an expert writing coach and communication analyst.

I will give you {count} cover letters written by the same person for different job applications.

Analyse them deeply and extract:

1. **Tone and voice**: formal vs. warm, confident vs. humble, academic vs. industry
2. **Typical structure**: how do they open? What comes in the middle? How do they close?
3. **Strengths highlighted**: which personal strengths/achievements appear repeatedly?
4. **Projects/experiences mentioned frequently**: which specific work or projects keep appearing?
5. **Characteristic phrases or sentences**: 3-5 phrases/patterns that are signature for this writer
6. **Opening hooks**: what types of opening sentences do they use?
7. **Call-to-action closings**: how do they end letters?
8. **Language style**: sentence length, use of technical jargon, formality markers
9. **What to replicate**: what makes these letters effective?
10. **What to avoid**: any patterns that feel weak or generic?

Return a JSON object:
{
  "tone": "confident-academic with warmth — mixes technical precision with personal motivation",
  "structure_pattern": ["opening: motivation + role-company connection", "middle: 2-3 achievement stories mapped to requirements", "closing: contribution promise + CTA"],
  "recurring_strengths": ["energy systems expertise", "Python/ML applied to energy", "research experience at Fraunhofer", "thesis on smart grids"],
  "frequently_mentioned_projects": ["thesis on power system optimisation", "Fraunhofer internship", "working student at E.ON"],
  "characteristic_phrases": ["at the intersection of energy and technology", "my thesis on...", "I am particularly drawn to..."],
  "sample_openings": ["exact opening from best letter 1", "exact opening from best letter 2"],
  "sample_closings": ["exact closing from best letter 1"],
  "sentence_style": "medium-length sentences, technical terms used confidently, avoids overused buzzwords",
  "effective_patterns": ["always connects personal motivation to company mission", "quantifies where possible"],
  "avoid_patterns": ["generic 'I am very motivated' without specifics"],
  "language": "de/en/mixed",
  "overall_quality": "strong — clear differentiation between applications"
}

COVER LETTERS:
{letters_text}
"""


class CoverLetterLearner:
    """Analyses existing cover letters to learn the user's writing style."""

    def __init__(self):
        self.client = AzureOpenAI(
            azure_endpoint=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            api_version=settings.llm_api_version,
        )
        self.model_name = settings.llm_model_name

    def extract_texts(self, folder: str | Path) -> List[dict]:
        """
        Extract text from all PDF/docx cover letters in a folder.
        Returns list of {filename, text}.
        """
        folder = Path(folder)
        if not folder.exists():
            raise FileNotFoundError(f"Cover letters folder not found: {folder}")

        results = []
        for ext in ["*.pdf", "*.PDF", "*.docx", "*.doc", "*.txt"]:
            for f in sorted(folder.glob(ext)):
                try:
                    if f.suffix.lower() == ".pdf":
                        text = extract_text_from_pdf(f)
                    elif f.suffix.lower() in (".docx", ".doc"):
                        text = _extract_docx(f)
                    else:
                        text = f.read_text(encoding="utf-8", errors="ignore")

                    if text and len(text.strip()) > 100:
                        results.append({"filename": f.name, "text": text.strip()})
                        logger.info(f"[StyleLearner] Extracted: {f.name} ({len(text)} chars)")
                except Exception as e:
                    logger.warning(f"[StyleLearner] Failed to read {f.name}: {e}")

        logger.info(f"[StyleLearner] Total cover letters loaded: {len(results)}")
        return results

    def analyse_style(self, letter_dicts: List[dict]) -> dict:
        """
        Call LLM to analyse writing style across all cover letters.
        Returns the style analysis dict.
        """
        if not letter_dicts:
            raise ValueError("No cover letters provided for analysis")

        # Build combined text — include filename as header, truncate each letter
        combined = ""
        for i, ld in enumerate(letter_dicts, 1):
            text = ld["text"][:1800]  # cap each letter to stay within token budget
            combined += f"\n\n--- LETTER {i}: {ld['filename']} ---\n{text}"

        # Cap total
        if len(combined) > 28000:
            combined = combined[:28000]
            logger.warning("[StyleLearner] Combined text truncated to 28k chars")

        prompt = STYLE_ANALYSIS_PROMPT.format(
            count=len(letter_dicts),
            letters_text=combined,
        )

        logger.info(f"[StyleLearner] Analysing {len(letter_dicts)} cover letters for style...")

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": "You are an expert writing coach. Analyse precisely."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            **get_token_kwargs(self.model_name, 2048),
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)
        logger.info(f"[StyleLearner] Style analysis complete. Tone: {data.get('tone', 'N/A')[:60]}")
        return data

    async def learn_and_store(self, folder: str | Path) -> "CoverLetterStyle":
        """
        Full pipeline: read folder → extract text → analyse → persist to DB.
        Returns the stored CoverLetterStyle ORM object.
        """
        folder = Path(folder)
        letter_dicts = self.extract_texts(folder)
        if not letter_dicts:
            raise ValueError(f"No readable cover letters found in: {folder}")

        style = self.analyse_style(letter_dicts)

        async with get_session() as session:
            from sqlalchemy import select

            # Upsert — only one style row per user
            result = await session.execute(
                select(CoverLetterStyle).order_by(CoverLetterStyle.learned_at.desc()).limit(1)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.style_summary = style.get("tone", "")
                existing.tone_markers = style.get("characteristic_phrases", [])
                existing.structure_pattern = style.get("structure_pattern", [])
                existing.strengths_highlighted = style.get("recurring_strengths", [])
                existing.sample_openings = style.get("sample_openings", [])
                existing.sample_closings = style.get("sample_closings", [])
                existing.raw_analysis = style
                existing.sample_count = len(letter_dicts)
                existing.source_files = [d["filename"] for d in letter_dicts]
                from datetime import datetime
                existing.learned_at = datetime.utcnow()
                session.add(existing)
                obj = existing
            else:
                obj = CoverLetterStyle(
                    style_summary=style.get("tone", ""),
                    tone_markers=style.get("characteristic_phrases", []),
                    structure_pattern=style.get("structure_pattern", []),
                    strengths_highlighted=style.get("recurring_strengths", []),
                    sample_openings=style.get("sample_openings", []),
                    sample_closings=style.get("sample_closings", []),
                    raw_analysis=style,
                    sample_count=len(letter_dicts),
                    source_files=[d["filename"] for d in letter_dicts],
                )
                session.add(obj)

            await session.flush()
            await session.refresh(obj)

        logger.info(
            f"[StyleLearner] Style stored. Samples: {obj.sample_count} | "
            f"Strengths: {len(obj.strengths_highlighted)}"
        )
        return obj

    @staticmethod
    async def get_style() -> Optional["CoverLetterStyle"]:
        """Load the stored style (if any)."""
        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(CoverLetterStyle)
                .order_by(CoverLetterStyle.learned_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    @staticmethod
    def format_style_for_prompt(style: "CoverLetterStyle") -> str:
        """Format the learned style into a concise prompt injection."""
        if not style:
            return ""
        parts = [
            f"WRITING STYLE GUIDANCE (learned from {style.sample_count} real cover letters by this candidate):",
            f"Tone: {style.style_summary}",
        ]
        if style.structure_pattern:
            parts.append(f"Structure: {' → '.join(style.structure_pattern[:4])}")
        if style.strengths_highlighted:
            parts.append(f"Typically emphasises: {', '.join(style.strengths_highlighted[:5])}")
        if style.sample_openings:
            parts.append(f"Example opening (replicate style, not content): \"{style.sample_openings[0]}\"")
        if style.sample_closings:
            parts.append(f"Example closing: \"{style.sample_closings[0]}\"")
        if style.tone_markers:
            parts.append(f"Characteristic phrases to draw from: {'; '.join(style.tone_markers[:3])}")
        raw = style.raw_analysis or {}
        if raw.get("effective_patterns"):
            parts.append(f"What works: {'; '.join(raw['effective_patterns'][:2])}")
        if raw.get("avoid_patterns"):
            parts.append(f"Avoid: {'; '.join(raw['avoid_patterns'][:2])}")
        return "\n".join(parts)


def _extract_docx(path: Path) -> str:
    """Extract text from a .docx file."""
    try:
        import zipfile
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(path) as z:
            with z.open("word/document.xml") as f:
                tree = ET.parse(f)
                root = tree.getroot()
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                paragraphs = root.findall(".//w:p", ns)
                return "\n".join(
                    "".join(t.text or "" for t in p.findall(".//w:t", ns))
                    for p in paragraphs
                )
    except Exception:
        return ""

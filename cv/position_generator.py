"""
Position Generator
==================
Analyses the FULL CV (education, skills, experience, projects, publications,
languages, certifications) and generates a prioritised list of suitable
job titles/keywords for searching.

Workflow:
  1. python main.py suggest-positions --cv cv.pdf
     → Analyses CV, writes output/suggested_positions.yaml
  2. User reviews and edits the YAML file
  3. python main.py scrape-from-suggestions
     → Reads approved positions and runs scrape

The LLM is instructed to think semantically — e.g. an MSc in Energy +
Python skills → "Energy Data Scientist", "Grid AI Engineer", etc.,
not just titles that literally appear in the CV.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import yaml
from loguru import logger
from core.llm_client import get_llm_client

from core.config import settings, get_token_kwargs
from core.models import CVProfileSchema

POSITION_PROMPT = """\
You are an expert career strategist and job market analyst.

Analyse the candidate's COMPLETE profile and generate a comprehensive list of
job titles/search keywords they should use to find the BEST matching positions.

IMPORTANT RULES:
- Think SEMANTICALLY, not just by job titles from the CV
- Consider their EDUCATION field and level (MSc/PhD opens specific doors)
- Consider combinations: e.g. Energy + AI → "Energy AI Engineer", "Grid Intelligence Analyst"
- Include German-language titles for German market (e.g. "Energieinformatiker", "KI Ingenieur")
- Include research roles if candidate has academic background
- Include adjacent/growth roles they could reasonably apply to
- Think about company types: startups, corporations, research institutes, consultancies
- Consider the German job market specifically (BA, StepStone, XING naming conventions)

Return a JSON object with this EXACT structure:
{{
  "primary": [
    {{
      "title": "Data Engineer",
      "title_de": "Data Engineer",
      "rationale": "Core match with Python + data pipeline experience",
      "confidence": 0.95,
      "target_sectors": ["Energy", "Tech", "Research"],
      "seniority": "junior/mid"
    }}
  ],
  "adjacent": [
    {{
      "title": "MLOps Engineer",
      "title_de": "MLOps Ingenieur",
      "rationale": "Stretch role — strong Python but needs more DevOps",
      "confidence": 0.70,
      "target_sectors": ["Tech", "Automotive"],
      "seniority": "mid"
    }}
  ],
  "research": [
    {{
      "title": "Research Software Engineer",
      "title_de": "Wissenschaftlicher Softwareentwickler",
      "rationale": "Ideal for Fraunhofer/DFG/Max Planck — research background",
      "confidence": 0.90,
      "target_sectors": ["Research Institutes", "Universities"],
      "seniority": "researcher"
    }}
  ],
  "german_specific": [
    {{
      "title": "Werkstudent Energietechnik",
      "title_de": "Werkstudent Energietechnik",
      "rationale": "Part-time student role — energy engineering background",
      "confidence": 0.85,
      "target_sectors": ["Energy", "Utilities"],
      "seniority": "werkstudent"
    }}
  ],
  "keywords_for_search": [
    "Python Machine Learning",
    "Energiedaten Analyst",
    "KI Energiesysteme",
    "Predictive Maintenance Engineer"
  ],
  "avoid_titles": [
    "Frontend Developer — no web UI experience"
  ],
  "market_insight": "Brief paragraph on candidate's positioning in the German job market"
}}

CANDIDATE PROFILE:
{cv_full}
"""


class PositionGenerator:
    """Generates and manages job search position keywords from a CV."""

    DEFAULT_OUTPUT = Path("output/suggested_positions.yaml")

    def __init__(self):
        llm_client = get_llm_client(); self.client = llm_client.client; self.model_name = llm_client.model_name
        self.model_name = settings.llm_model_name

    def generate(self, cv_profile: CVProfileSchema) -> dict:
        """
        Call LLM to generate position suggestions from the full CV profile.
        Returns the raw suggestions dict.
        """
        cv_full = self._build_full_cv_context(cv_profile)
        logger.info(f"[PositionGen] Generating positions for {cv_profile.full_name or 'candidate'}")

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system",
                 "content": "You are an expert career strategist with deep knowledge of the German job market."},
                {"role": "user", "content": POSITION_PROMPT.format(cv_full=cv_full)},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
            **get_token_kwargs(self.model_name, 3000),
        )

        raw = response.choices[0].message.content
        suggestions = json.loads(raw)
        logger.info(
            f"[PositionGen] Generated "
            f"{len(suggestions.get('primary', []))} primary, "
            f"{len(suggestions.get('adjacent', []))} adjacent, "
            f"{len(suggestions.get('research', []))} research roles"
        )
        return suggestions

    def save_for_review(
        self,
        suggestions: dict,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Save suggestions to a YAML file for user review.
        User edits this file, then runs scrape-from-suggestions.
        """
        out = output_path or self.DEFAULT_OUTPUT
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Build the review-friendly YAML structure
        review_doc = {
            "instructions": (
                "Review and edit these position suggestions.\n"
                "Set 'approved: true' for positions you want to search for.\n"
                "Set 'approved: false' to skip.\n"
                "Add new positions manually under any category.\n"
                "Then run: python main.py scrape-from-suggestions"
            ),
            "market_insight": suggestions.get("market_insight", ""),
            "primary_roles": [
                {
                    "title": p["title"],
                    "title_de": p.get("title_de", ""),
                    "rationale": p.get("rationale", ""),
                    "confidence": p.get("confidence", 0),
                    "sectors": p.get("target_sectors", []),
                    "seniority": p.get("seniority", ""),
                    "approved": True,   # Primary roles approved by default
                }
                for p in suggestions.get("primary", [])
            ],
            "adjacent_roles": [
                {
                    "title": p["title"],
                    "title_de": p.get("title_de", ""),
                    "rationale": p.get("rationale", ""),
                    "confidence": p.get("confidence", 0),
                    "sectors": p.get("target_sectors", []),
                    "seniority": p.get("seniority", ""),
                    "approved": False,  # Adjacent roles need explicit approval
                }
                for p in suggestions.get("adjacent", [])
            ],
            "research_roles": [
                {
                    "title": p["title"],
                    "title_de": p.get("title_de", ""),
                    "rationale": p.get("rationale", ""),
                    "confidence": p.get("confidence", 0),
                    "sectors": p.get("target_sectors", []),
                    "seniority": p.get("seniority", ""),
                    "approved": True,   # Research roles approved (likely relevant)
                }
                for p in suggestions.get("research", [])
            ],
            "german_specific_roles": [
                {
                    "title": p["title"],
                    "title_de": p.get("title_de", ""),
                    "rationale": p.get("rationale", ""),
                    "confidence": p.get("confidence", 0),
                    "seniority": p.get("seniority", ""),
                    "approved": True,
                }
                for p in suggestions.get("german_specific", [])
            ],
            "extra_search_keywords": suggestions.get("keywords_for_search", []),
            "avoid_titles": suggestions.get("avoid_titles", []),
        }

        with open(out, "w", encoding="utf-8") as f:
            yaml.dump(review_doc, f, allow_unicode=True, default_flow_style=False,
                      sort_keys=False, width=120)

        logger.info(f"[PositionGen] Saved suggestions to: {out}")
        return out

    @staticmethod
    def load_approved(path: Optional[Path] = None) -> List[str]:
        """
        Read the user-edited YAML and return approved position titles
        (both English and German, deduplicated).
        """
        p = Path(path or PositionGenerator.DEFAULT_OUTPUT)
        if not p.exists():
            raise FileNotFoundError(
                f"Suggestions file not found: {p}\n"
                f"Run: python main.py suggest-positions --cv your_cv.pdf"
            )

        with open(p, encoding="utf-8") as f:
            doc = yaml.safe_load(f)

        approved = []
        for category in ["primary_roles", "adjacent_roles", "research_roles",
                          "german_specific_roles"]:
            for role in doc.get(category, []):
                if role.get("approved", False):
                    title = role.get("title", "").strip()
                    title_de = role.get("title_de", "").strip()
                    if title:
                        approved.append(title)
                    if title_de and title_de != title:
                        approved.append(title_de)

        # Extra keywords
        for kw in doc.get("extra_search_keywords", []):
            if isinstance(kw, str) and kw.strip():
                approved.append(kw.strip())

        # Deduplicate preserving order
        seen = set()
        result = []
        for p in approved:
            if p.lower() not in seen:
                seen.add(p.lower())
                result.append(p)

        logger.info(f"[PositionGen] Loaded {len(result)} approved positions")
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_full_cv_context(self, cv: CVProfileSchema) -> str:
        """
        Build a comprehensive CV context — more complete than get_cv_summary_for_llm.
        Includes publications, projects, ALL education details, ALL skills.
        """
        parts = []

        if cv.full_name:
            parts.append(f"Name: {cv.full_name}")
        if cv.location:
            parts.append(f"Location: {cv.location}")
        if cv.summary:
            parts.append(f"\nProfessional Summary:\n{cv.summary}")

        # ALL skills
        if cv.skills:
            parts.append(f"\nAll Skills ({len(cv.skills)}):\n  {', '.join(cv.skills)}")

        # Languages
        if cv.languages:
            lang_str = ", ".join(
                f"{l.get('language', '')} ({l.get('proficiency', '')})"
                for l in cv.languages
            )
            parts.append(f"Languages: {lang_str}")

        # Full education (all degrees, grades, fields)
        if cv.education:
            parts.append("\nEducation:")
            for edu in cv.education:
                grade = f", Grade: {edu.get('grade')}" if edu.get("grade") else ""
                thesis = f"\n    Thesis/Focus: {edu.get('thesis', '')}" if edu.get("thesis") else ""
                parts.append(
                    f"  - {edu.get('degree')} in {edu.get('field')}\n"
                    f"    Institution: {edu.get('institution')}\n"
                    f"    Period: {edu.get('start_date', '')} – {edu.get('end_date', '')}"
                    f"{grade}{thesis}"
                )

        # Full work experience (all positions with descriptions)
        if cv.work_experience:
            parts.append("\nWork Experience:")
            for exp in cv.work_experience:
                start = exp.get("start_date", "")
                end = exp.get("end_date", "Present")
                desc = exp.get("description", "")
                achievements = exp.get("achievements", [])
                parts.append(
                    f"  - {exp.get('title')} at {exp.get('company')} "
                    f"({start} – {end})"
                )
                if desc:
                    parts.append(f"    {desc[:400]}")
                for ach in achievements[:3]:
                    parts.append(f"    • {ach[:200]}")

        # Certifications
        if cv.certifications:
            parts.append(f"\nCertifications: {', '.join(cv.certifications)}")

        # Projects (from raw_text if not in schema)
        # Try to extract from raw_text if available
        if cv.raw_text and "project" in cv.raw_text.lower():
            # Include a slice of raw text that might have projects/publications
            idx = cv.raw_text.lower().find("project")
            if idx != -1:
                snippet = cv.raw_text[idx:idx+800]
                parts.append(f"\nProjects / Publications (extracted):\n{snippet}")

        return "\n".join(parts)

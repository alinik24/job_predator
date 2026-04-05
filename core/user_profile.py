"""
User Profile Manager
====================
Manages a structured self-description that goes BEYOND the CV.

This is where the user adds:
  - Personal motivation, career goals, values
  - Context for specific experiences ("what I really learned", "what I'm proud of")
  - Skills with concrete evidence (project-level proof)
  - Preferences that shape cover letter tone
  - Personal notes for the AI to use during application

The profile lives in output/user_profile.yaml — the user edits it directly.
The agent reads it and injects relevant parts into cover letter prompts.

Commands:
  python main.py profile               — show current profile
  python main.py profile --init        — create blank template
  python main.py profile --add-context — guided context addition
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from loguru import logger

DEFAULT_PATH = Path("output/user_profile.yaml")

TEMPLATE = {
    "instructions": (
        "Fill out this file — it teaches the AI about YOU beyond what's in your CV.\n"
        "The more you fill in, the more personalised your cover letters become.\n"
        "All fields are optional but highly recommended."
    ),
    "personal": {
        "name": "",
        "current_status": "e.g. MSc student, looking for thesis/working student position",
        "nationality": "",
        "languages_spoken": ["German (B2/C1)", "English (C1)", "Persian (native)"],
        "location_flexibility": "Willing to relocate within Germany; prefer NRW/Bavaria",
        "work_authorisation": "Student visa — can work up to 20hrs/week; seeking full-time after graduation",
    },
    "career_goals": [
        "Work at the intersection of energy systems and AI/ML",
        "Contribute to Germany's energy transition (Energiewende)",
        "Ideally research + engineering hybrid role",
        "Long-term: lead data/AI projects in energy or climate tech",
    ],
    "motivation_statement": (
        "In 2-3 sentences: why this field? What drives you?\n"
        "Example: I am passionate about applying AI to accelerate the energy transition. "
        "Having studied energy systems engineering and worked at Fraunhofer, I want to bridge "
        "the gap between research and real-world grid operations."
    ),
    "experience_context": [
        {
            "role": "Working Student / Intern at Fraunhofer [Institute Name]",
            "company": "Fraunhofer-Gesellschaft",
            "context": "What did you actually work on? What did you learn? What are you most proud of?",
            "key_achievement": "Optional: specific quantifiable achievement",
            "technologies_used": ["Python", "pandas", "scikit-learn"],
        }
    ],
    "thesis_context": {
        "topic": "Your thesis topic",
        "motivation": "Why did you choose this topic?",
        "key_contribution": "What is the novel contribution?",
        "technologies": ["Python", "PowerFactory", "MATLAB"],
        "relevance_to_job_market": "How does this connect to industry needs?",
    },
    "skills_with_evidence": [
        {
            "skill": "Python",
            "proficiency": "advanced",
            "evidence": "5+ years, used extensively in thesis for smart grid simulation and ML models",
            "best_project": "Master thesis — power system optimisation using reinforcement learning",
        },
        {
            "skill": "Machine Learning",
            "proficiency": "intermediate-advanced",
            "evidence": "Applied in thesis for energy demand forecasting; scikit-learn, PyTorch basics",
            "best_project": "Predictive maintenance model for grid infrastructure at Fraunhofer",
        },
    ],
    "projects_not_in_cv": [
        {
            "name": "Project name",
            "description": "What did you build/research?",
            "technologies": ["Python", "etc."],
            "outcome": "Result, publication, or demo",
        }
    ],
    "application_preferences": {
        "preferred_company_types": ["research institutes", "energy companies", "tech startups"],
        "preferred_company_sizes": ["startup to mid-size", "large research organisations"],
        "preferred_sectors": ["energy", "climate tech", "AI/ML", "power systems"],
        "avoid_sectors": ["defense", "pure finance"],
        "min_salary_gross_eur": 45000,
        "remote_preference": "hybrid (2-3 days remote)",
        "contract_type": "full-time or thesis student or working student",
        "earliest_start_date": "immediately / after thesis submission",
    },
    "cover_letter_preferences": {
        "language": "de",
        "tone": "professional but warm — not overly formal",
        "length": "one page",
        "always_mention": [
            "connection between my energy background and the specific role",
            "concrete project or achievement relevant to the job",
        ],
        "avoid_mentioning": [
            "generic phrases like 'highly motivated team player'",
        ],
    },
    "personal_values_and_culture_fit": [
        "I value mission-driven work — I want my work to have real-world impact",
        "I thrive in collaborative, interdisciplinary teams",
        "I appreciate flat hierarchies and open knowledge-sharing culture",
    ],
    "additional_context": (
        "Anything else the AI should know about you that isn't covered above.\n"
        "For example: gap year explanation, special circumstances, awards, publications, etc."
    ),
}


class UserProfileManager:
    """Manages the user's self-description profile (output/user_profile.yaml)."""

    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def init(self, overwrite: bool = False) -> Path:
        """Create a blank profile template."""
        if self.path.exists() and not overwrite:
            logger.info(f"[Profile] Profile already exists at {self.path}")
            return self.path

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(
                TEMPLATE,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                width=120,
            )
        logger.info(f"[Profile] Created blank template at {self.path}")
        return self.path

    def load(self) -> dict:
        """Load the user profile YAML."""
        if not self.path.exists():
            logger.warning(f"[Profile] No profile found at {self.path} — using empty profile")
            return {}
        with open(self.path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def build_context_for_llm(self, job_description: str = "") -> str:
        """
        Build a rich context string to inject into cover letter / scoring prompts.
        If job_description is provided, emphasises the most relevant sections.
        """
        profile = self.load()
        if not profile or "instructions" in profile and len(profile) <= 2:
            return ""

        parts = []

        personal = profile.get("personal", {})
        if personal.get("name"):
            parts.append(f"Name: {personal['name']}")
        if personal.get("current_status"):
            parts.append(f"Status: {personal['current_status']}")
        if personal.get("work_authorisation"):
            parts.append(f"Work authorisation: {personal['work_authorisation']}")

        if profile.get("motivation_statement") and "Example:" not in str(profile.get("motivation_statement", "")):
            parts.append(f"\nPersonal Motivation:\n{profile['motivation_statement']}")

        goals = profile.get("career_goals", [])
        if goals and isinstance(goals, list):
            parts.append(f"\nCareer Goals: {'; '.join(str(g) for g in goals[:4])}")

        # Experience context — most valuable for tailoring
        exp_context = profile.get("experience_context", [])
        if exp_context and isinstance(exp_context, list):
            parts.append("\nExperience Context (beyond CV):")
            for exp in exp_context[:3]:
                if isinstance(exp, dict) and exp.get("role") and "Insert" not in str(exp.get("role", "")):
                    parts.append(f"  [{exp['role']} @ {exp.get('company', '')}]")
                    if exp.get("context") and "What did you" not in str(exp.get("context", "")):
                        parts.append(f"    Context: {exp['context'][:300]}")
                    if exp.get("key_achievement"):
                        parts.append(f"    Achievement: {exp['key_achievement']}")

        # Thesis context — critical for research/engineering applications
        thesis = profile.get("thesis_context", {})
        if thesis and isinstance(thesis, dict) and thesis.get("topic") and "Your thesis" not in str(thesis.get("topic", "")):
            parts.append(f"\nThesis: {thesis['topic']}")
            if thesis.get("key_contribution"):
                parts.append(f"  Contribution: {thesis['key_contribution']}")
            if thesis.get("technologies"):
                parts.append(f"  Technologies: {', '.join(thesis['technologies'][:6])}")

        # Skills with evidence
        skills = profile.get("skills_with_evidence", [])
        if skills and isinstance(skills, list):
            parts.append("\nSkills with Evidence:")
            for sk in skills[:5]:
                if isinstance(sk, dict) and sk.get("skill"):
                    evidence = sk.get("evidence", "")
                    if evidence and "Used in thesis" not in evidence:
                        parts.append(f"  {sk['skill']} ({sk.get('proficiency', '')}): {evidence[:150]}")

        # Application preferences
        prefs = profile.get("application_preferences", {})
        if prefs.get("remote_preference"):
            parts.append(f"\nRemote preference: {prefs['remote_preference']}")
        if prefs.get("earliest_start_date"):
            parts.append(f"Availability: {prefs['earliest_start_date']}")

        # Values
        values = profile.get("personal_values_and_culture_fit", [])
        if values and isinstance(values, list):
            filtered = [v for v in values if isinstance(v, str) and "I value" in v or "I thrive" in v or "I appreciate" in v]
            if filtered:
                parts.append(f"\nValues: {'; '.join(filtered[:2])}")

        additional = profile.get("additional_context", "")
        if additional and "Anything else" not in str(additional):
            parts.append(f"\nAdditional context: {str(additional)[:400]}")

        return "\n".join(parts)

    def get_cover_letter_preferences(self) -> dict:
        """Return cover letter generation preferences."""
        profile = self.load()
        return profile.get("cover_letter_preferences", {
            "language": "de",
            "tone": "professional",
            "length": "one page",
        })

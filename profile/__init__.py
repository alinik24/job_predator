"""
Profile System
==============

This package provides access to the user's digital CV and cover letter rules.

Modules:
- cv_reader: Parse and query the markdown-based CV
- cover_letter_rules: Load and access cover letter master prompt rules
"""

from .cv_reader import (
    CVData,
    CVReader,
    get_cv,
    get_cv_section,
    search_cv,
    get_cv_skills,
    get_cv_projects,
)

from .cover_letter_rules import (
    CoverLetterRules,
    get_master_prompt,
    get_fixed_education,
    get_fixed_closing,
    get_project_selection_rules,
    format_prompt_with_job,
)

__all__ = [
    # CV Reader
    "CVData",
    "CVReader",
    "get_cv",
    "get_cv_section",
    "search_cv",
    "get_cv_skills",
    "get_cv_projects",
    # Cover Letter Rules
    "CoverLetterRules",
    "get_master_prompt",
    "get_fixed_education",
    "get_fixed_closing",
    "get_project_selection_rules",
    "format_prompt_with_job",
]

"""
Knowledge Base Learner - Extract patterns from existing cover letters.

Analyzes PDF cover letters to build a learned KB mapping:
- Job types → Projects mentioned
- Job types → Skills emphasized
- Job types → Experience highlighted
"""

import re
from pathlib import Path
from typing import Dict, List, Set
import pypdf


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF cover letter."""
    try:
        reader = pypdf.PdfReader(str(pdf_path))
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        print(f"Error reading {pdf_path.name}: {e}")
        return ""


def infer_job_category(filename: str, text: str) -> str:
    """Infer job category from filename and content."""
    filename_lower = filename.lower()
    text_lower = text.lower()

    # Map filenames and keywords to categories
    if any(kw in filename_lower for kw in ['algo', 'trading', 'fintech', 'financial']):
        return "FinTech/Finance"
    elif any(kw in filename_lower for kw in ['energy', 'grid', 'renewable', 'electrolysis', 'hydrogen']):
        return "Energy Systems"
    elif any(kw in filename_lower for kw in ['ml', 'ai', 'optimization', 'machine_learning']):
        return "AI/ML"
    elif any(kw in filename_lower for kw in ['software', 'developer', 'engineer']):
        return "Software Engineering"
    elif 'fraunhofer' in filename_lower:
        # Check content for specifics
        if any(kw in text_lower for kw in ['electrolysis', 'hydrogen', 'energy']):
            return "Energy Systems"
        elif any(kw in text_lower for kw in ['machine learning', 'optimization', 'ai']):
            return "AI/ML"
        return "Research"
    elif any(kw in filename_lower for kw in ['phd', 'research', 'thesis']):
        # Check content
        if 'energy' in text_lower or 'power system' in text_lower:
            return "Energy Systems"
        elif 'machine learning' in text_lower or 'optimization' in text_lower:
            return "AI/ML"
        return "Research"

    return "General"


def extract_mentioned_projects(text: str) -> Set[str]:
    """Extract project names mentioned in cover letter using semantic matching."""
    projects = set()
    text_lower = text.lower()

    # Map project keywords to project names from CV
    project_patterns = {
        "FORVIA HELLA / SMT Production": ["forvia", "hella", "smt", "pcb", "quality modeling", "defect detection", "manufacturing"],
        "Benteler": ["benteler", "excel digitalization", "project management", "rag"],
        "HIK Electrical Schema": ["electrical schema", "hik", "digitalization", "automation"],
        "Battery Cell Production": ["battery", "cell production", "parameter identification"],
        "Legal-Tech SaaS": ["legal-tech", "saas platform", "administrative automation"],
        "Personalized Deep-Research": ["deep-research", "idea scouting", "market analysis", "personalized"],
        "Senior+ HR Platform": ["senior+", "hr platform", "onboarding"],
        "Public Sector Platform": ["public sector", "administrative digitalization"],
        "DüsselPulse": ["düsselpulse", "smart city"],
        "Solar Desalination": ["desalination", "ro-med", "solar-powered"],
        "Wind Turbine CFD": ["wind turbine", "aerodynamic", "cfd", "openfoam"],
        "Geothermal Power": ["geothermal", "sustainable transition"],
        "Tidal Energy": ["tidal energy", "hydrodynamic"],
        "Hybrid Microgrid": ["microgrid", "renewable", "namibia", "homer"],
        "Energy Audit Rome": ["energy audit", "campus", "optimization"],
        "Hydrogen Electrolysis": ["electrolyzer", "hydrogen", "green hydrogen", "solid oxide"],
        "Flare Gas Recovery": ["flare gas", "recovery", "refinery"],
        "Reformer Unit": ["reformer", "petrochemical"],
    }

    for project_name, keywords in project_patterns.items():
        # Check if any keywords match
        if any(kw in text_lower for kw in keywords):
            projects.add(project_name)

    return projects


def extract_mentioned_skills(text: str) -> Set[str]:
    """Extract skills mentioned in cover letter."""
    skills = set()

    # Technical skills to look for
    known_skills = [
        "Python", "R", "SQL", "C++", "MATLAB", "Julia",
        "PyTorch", "TensorFlow", "Keras", "scikit-learn",
        "Pandas", "NumPy", "Polars", "PySpark",
        "PostgreSQL", "BigQuery", "DuckDB",
        "Docker", "Git", "Linux",
        "Machine Learning", "Deep Learning", "NLP",
        "Data Analysis", "Statistical Modeling",
        "Energy Systems", "Power Systems", "Grid Optimization",
        "Renewable Energy", "Battery Storage",
    ]

    text_lower = text.lower()
    for skill in known_skills:
        if skill.lower() in text_lower:
            skills.add(skill)

    return skills


def analyze_cover_letters(cover_letters_dir: Path) -> Dict[str, Dict]:
    """Analyze all cover letters and build learned KB."""
    kb = {}

    pdf_files = list(cover_letters_dir.glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF cover letters\n")

    for pdf_file in pdf_files:
        print(f"Analyzing: {pdf_file.name}")

        text = extract_text_from_pdf(pdf_file)
        if not text:
            continue

        category = infer_job_category(pdf_file.name, text)
        projects = extract_mentioned_projects(text)
        skills = extract_mentioned_skills(text)

        print(f"  Category: {category}")
        print(f"  Projects: {projects}")
        print(f"  Skills: {skills}")
        print()

        # Aggregate by category
        if category not in kb:
            kb[category] = {
                'projects': set(),
                'skills': set(),
                'count': 0
            }

        kb[category]['projects'].update(projects)
        kb[category]['skills'].update(skills)
        kb[category]['count'] += 1

    return kb


def main():
    """Main entry point."""
    cover_letters_dir = Path("user_documents/cover_letters")

    if not cover_letters_dir.exists():
        print(f"Cover letters directory not found: {cover_letters_dir}")
        return

    kb = analyze_cover_letters(cover_letters_dir)

    print("\n" + "="*80)
    print("LEARNED KNOWLEDGE BASE SUMMARY")
    print("="*80)

    for category, data in sorted(kb.items()):
        print(f"\n{category} ({data['count']} applications):")
        print(f"  Projects: {sorted(data['projects'])}")
        print(f"  Skills: {sorted(data['skills'])}")


if __name__ == "__main__":
    main()

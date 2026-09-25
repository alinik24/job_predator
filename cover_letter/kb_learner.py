"""
Knowledge Base Learner - Extract patterns from existing cover letters.

Analyzes PDF cover letters to build a learned KB mapping:
- Job types → Projects mentioned
- Job types → Skills emphasized
- Job types → Experience highlighted

Supports continuous learning:
- Analyzes existing cover letters on first run
- Updates KB when new cover letters are confirmed
- Tracks analyzed files to avoid re-processing
"""

import re
from pathlib import Path
from typing import Dict, List, Set
from datetime import datetime
import pypdf
import yaml


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


def load_existing_kb(kb_file: Path) -> Dict:
    """Load existing KB from YAML file if it exists."""
    if not kb_file.exists():
        return {
            'metadata': {
                'created': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'analyzed_files': []
            },
            'categories': {}
        }

    with open(kb_file, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
        if not data:
            return {
                'metadata': {
                    'created': datetime.now().isoformat(),
                    'last_updated': datetime.now().isoformat(),
                    'analyzed_files': []
                },
                'categories': {}
            }
        return data


def merge_kb_data(existing_kb: Dict, new_data: Dict[str, Dict]) -> Dict:
    """Merge new analysis data into existing KB."""
    categories = existing_kb.get('categories', {})

    for category, data in new_data.items():
        if category not in categories:
            categories[category] = {
                'projects': [],
                'skills': [],
                'count': 0
            }

        # Merge projects (avoid duplicates)
        existing_projects = set(categories[category].get('projects', []))
        new_projects = data['projects']
        categories[category]['projects'] = sorted(existing_projects.union(new_projects))

        # Merge skills (avoid duplicates)
        existing_skills = set(categories[category].get('skills', []))
        new_skills = data['skills']
        categories[category]['skills'] = sorted(existing_skills.union(new_skills))

        # Update count
        categories[category]['count'] = categories[category].get('count', 0) + data['count']

    existing_kb['categories'] = categories
    existing_kb['metadata']['last_updated'] = datetime.now().isoformat()

    return existing_kb


def save_kb_to_yaml(kb: Dict, output_file: Path):
    """Save KB to YAML file with professional structure."""
    # Build YAML structure
    yaml_content = f"""# Knowledge Base - Learned from historical cover letters
# Created: {kb['metadata']['created']}
# Last Updated: {kb['metadata']['last_updated']}
# Total Files Analyzed: {len(kb['metadata']['analyzed_files'])}
#
# This KB is automatically learned by analyzing which projects, skills, and
# experience were emphasized in past applications for each job category.

position_categories:
"""

    # Sort categories by application count (descending)
    sorted_categories = sorted(
        kb['categories'].items(),
        key=lambda x: x[1]['count'],
        reverse=True
    )

    for category_name, category_data in sorted_categories:
        yaml_content += f"""
  - category: "{category_name}"
    applications_analyzed: {category_data['count']}

    # Projects historically used for {category_name} positions
    projects:
"""

        projects = category_data.get('projects', [])
        if projects:
            for project in projects:
                yaml_content += f"""      - "{project}"
"""
        else:
            yaml_content += """      []
"""

        yaml_content += f"""
    # Skills historically emphasized
    skills:
"""

        skills = category_data.get('skills', [])
        if skills:
            for skill in skills:
                yaml_content += f"""      - "{skill}"
"""
        else:
            yaml_content += """      []
"""

    # Save to file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(yaml_content)

    print(f"\n[OK] KB saved to {output_file}")


def update_kb_from_new_letter(pdf_path: Path, kb_file: Path = Path("cover_letter/kb_mappings.yaml")):
    """
    Update KB with a newly generated cover letter after user confirmation.

    Usage:
        After generating and user confirms a cover letter:
        update_kb_from_new_letter(Path("cover_letter/output/Ali_Nazarikhah_Cover_Letter_XYZ.pdf"))
    """
    # Load existing KB
    existing_kb = load_existing_kb(kb_file)

    # Check if already analyzed
    if str(pdf_path) in existing_kb['metadata']['analyzed_files']:
        print(f"Already analyzed: {pdf_path.name}")
        return

    # Analyze the new letter
    text = extract_text_from_pdf(pdf_path)
    if not text:
        print(f"Could not extract text from: {pdf_path.name}")
        return

    category = infer_job_category(pdf_path.name, text)
    projects = extract_mentioned_projects(text)
    skills = extract_mentioned_skills(text)

    print(f"\nLearning from: {pdf_path.name}")
    print(f"  Category: {category}")
    print(f"  Projects: {projects}")
    print(f"  Skills: {skills}")

    # Create new data structure
    new_data = {
        category: {
            'projects': projects,
            'skills': skills,
            'count': 1
        }
    }

    # Merge with existing KB
    updated_kb = merge_kb_data(existing_kb, new_data)

    # Track this file as analyzed
    updated_kb['metadata']['analyzed_files'].append(str(pdf_path))

    # Save updated KB
    save_kb_to_yaml(updated_kb, kb_file)

    print(f"✓ KB updated with new cover letter")


def rebuild_kb_from_scratch(
    cover_letters_dir: Path = Path("user_documents/cover_letters"),
    kb_file: Path = Path("cover_letter/kb_mappings.yaml")
):
    """
    Rebuild entire KB from scratch by analyzing all cover letters.

    Use this for initial KB creation or to reset the KB.
    """
    kb_data = analyze_cover_letters(cover_letters_dir)

    # Convert to structured format
    structured_kb = {
        'metadata': {
            'created': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'analyzed_files': [
                str(f) for f in cover_letters_dir.glob("*.pdf")
            ]
        },
        'categories': {}
    }

    for category, data in kb_data.items():
        structured_kb['categories'][category] = {
            'projects': sorted(data['projects']),
            'skills': sorted(data['skills']),
            'count': data['count']
        }

    # Save to YAML
    save_kb_to_yaml(structured_kb, kb_file)

    return structured_kb


def main():
    """Main entry point - rebuild KB from scratch."""
    cover_letters_dir = Path("user_documents/cover_letters")
    kb_file = Path("cover_letter/kb_mappings.yaml")

    if not cover_letters_dir.exists():
        print(f"Cover letters directory not found: {cover_letters_dir}")
        return

    print("="*80)
    print("REBUILDING KNOWLEDGE BASE FROM HISTORICAL COVER LETTERS")
    print("="*80)

    kb = rebuild_kb_from_scratch(cover_letters_dir, kb_file)

    print("\n" + "="*80)
    print("LEARNED KNOWLEDGE BASE SUMMARY")
    print("="*80)

    for category, data in sorted(kb['categories'].items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"\n{category} ({data['count']} applications):")
        print(f"  Projects: {data['projects']}")
        print(f"  Skills: {data['skills']}")

    print(f"\n✓ KB is now continuously learning from new cover letters")
    print(f"✓ Use update_kb_from_new_letter() to add newly generated cover letters")


if __name__ == "__main__":
    main()

import re

def parse_cv(cv_text):
    """Parse CV markdown and extract structured data for priority fields."""
    return {
        'projects': _extract_projects(cv_text),
        'experience': _extract_experience(cv_text),
        'skills': _extract_skills(cv_text),
        'education': _extract_education(cv_text),
        'research_interests': _extract_research_interests(cv_text)
    }

def _extract_projects(cv_text):
    """Extract projects organized by section (EiCS, EE, CE)."""
    projects = {}

    # Find Projects section (match until next top-level # section or end)
    projects_match = re.search(r'# Projects\s+(.*?)(?=\n# [^#]|\Z)', cv_text, re.DOTALL)
    if not projects_match:
        return projects

    projects_section = projects_match.group(1)

    # Find subsections like "## EiCS" (exactly 2 hashes, not 3+)
    subsections = re.finditer(r'## ([^\n]+)\s+(.*?)(?=\n## [^#]|\Z)', projects_section, re.DOTALL)

    for subsection in subsections:
        section_full_name = subsection.group(1).strip()
        # Extract key name (e.g., "EiCS" from "EiCS — Engineering in Computer Science")
        section_name = section_full_name.split('—')[0].strip() if '—' in section_full_name else section_full_name
        section_content = subsection.group(2)

        # Extract individual projects (### Project Name)
        project_matches = re.finditer(r'### ([^\n]+)\s+(.*?)(?=\n###|\Z)', section_content, re.DOTALL)

        section_projects = []
        for proj in project_matches:
            project_name = proj.group(1).strip()
            project_desc = proj.group(2).strip()

            section_projects.append({
                'name': project_name,
                'description': project_desc
            })

        if section_projects:
            projects[section_name] = section_projects

    return projects

def _extract_experience(cv_text):
    """Extract experience entries with role, organization, period, description."""
    experience = []

    # Find Experience section
    exp_match = re.search(r'# Experience\s+(.*?)(?=\n# [^#]|\Z)', cv_text, re.DOTALL)
    if not exp_match:
        return experience

    exp_section = exp_match.group(1)

    # Find each role (## Role Title)
    role_matches = re.finditer(r'## ([^\n]+)\s+(.*?)(?=\n## [^#]|\Z)', exp_section, re.DOTALL)

    for role in role_matches:
        role_name = role.group(1).strip()
        role_content = role.group(2)

        # Extract structured fields
        period = re.search(r'\*\*Period:\*\*\s*([^\n]+)', role_content)
        location = re.search(r'\*\*Location:\*\*\s*([^\n]+)', role_content)
        org = re.search(r'\*\*Organization:\*\*\s*([^\n]+)', role_content)

        # Extract description (text after last ** field)
        desc_match = re.search(r'\*\*Organization:\*\*[^\n]+\s+(.*)', role_content, re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else ''

        experience.append({
            'role': role_name,
            'period': period.group(1).strip() if period else '',
            'location': location.group(1).strip() if location else '',
            'organization': org.group(1).strip() if org else '',
            'description': description
        })

    return experience

def _extract_skills(cv_text):
    """Extract skills organized by section and subsection."""
    skills = {}

    # Find Skills section
    skills_match = re.search(r'# Skills\s+(.*?)(?=\n# [^#]|\Z)', cv_text, re.DOTALL)
    if not skills_match:
        return skills

    skills_section = skills_match.group(1)

    # Find major sections (## EiCS, ## EE & CE)
    major_sections = re.finditer(r'## ([^\n]+)\s+(.*?)(?=\n## [^#]|\Z)', skills_section, re.DOTALL)

    for major_sec in major_sections:
        major_name = major_sec.group(1).strip()
        major_content = major_sec.group(2)

        # Check for subsections (### AI/ML Engineering)
        subsection_matches = list(re.finditer(r'### ([^\n]+)\s+(.*?)(?=\n###|\Z)', major_content, re.DOTALL))

        if subsection_matches:
            # Has subsections
            skills[major_name] = {}
            for subsec in subsection_matches:
                subsec_name = subsec.group(1).strip()
                subsec_content = subsec.group(2).strip()
                skills[major_name][subsec_name] = subsec_content
        else:
            # No subsections, use content directly
            skills[major_name] = major_content.strip()

    return skills

def _extract_education(cv_text):
    """Extract education entries."""
    education = []

    # Find Education section
    edu_match = re.search(r'# Education\s+(.*?)(?=\n# [^#]|\Z)', cv_text, re.DOTALL)
    if not edu_match:
        return education

    edu_section = edu_match.group(1)

    # Find degree entries (## MSc, ## BSc)
    degree_matches = re.finditer(r'## ([^\n]+)\s+(.*?)(?=\n## [^#]|\Z)', edu_section, re.DOTALL)

    for degree in degree_matches:
        degree_name = degree.group(1).strip()
        degree_content = degree.group(2)

        # Extract fields
        period = re.search(r'\*\*Period:\*\*\s*([^\n]+)', degree_content)
        institution = re.search(r'\*\*Institution:\*\*\s*([^\n]+)', degree_content)
        details = re.search(r'\*\*Details:\*\*\s+(.*?)(?=\n\*\*|\Z)', degree_content, re.DOTALL)

        education.append({
            'degree': degree_name,
            'period': period.group(1).strip() if period else '',
            'institution': institution.group(1).strip() if institution else '',
            'details': details.group(1).strip() if details else ''
        })

    return education

def _extract_research_interests(cv_text):
    """Extract research interests organized by field."""
    interests = {}

    # Find Research Interests section
    interests_match = re.search(r'# Research Interests\s+(.*?)(?=\n# [^#]|\Z)', cv_text, re.DOTALL)
    if not interests_match:
        return interests

    interests_section = interests_match.group(1)

    # Find subsections (## EE, ## EiCS)
    subsections = re.finditer(r'## ([^\n]+)\s+(.*?)(?=\n## [^#]|\Z)', interests_section, re.DOTALL)

    for subsec in subsections:
        subsec_name = subsec.group(1).strip().split('—')[0].strip()  # Extract "EE" from "EE — Energy Engineering"
        subsec_content = subsec.group(2)

        # Extract bullet points
        bullet_points = re.findall(r'-\s*([^\n]+)', subsec_content)
        interests[subsec_name] = [point.strip() for point in bullet_points]

    return interests

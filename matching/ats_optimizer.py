"""
ATS (Applicant Tracking System) Optimizer
==========================================
Analyzes and optimizes resumes/cover letters for ATS systems.

Based on industry research:
- 75% of resumes never reach human recruiters (filtered by ATS)
- Keyword density, formatting, and structure are critical
- Different ATS systems (Taleo, Workday, Greenhouse, ICIMS) have different parsing quirks
"""

import re
from typing import List, Dict, Set, Tuple
from collections import Counter
import json
from loguru import logger


class ATSOptimizer:
    """
    Analyzes documents for ATS compatibility and suggests improvements.
    """

    # Common ATS systems and their quirks
    ATS_SYSTEMS = {
        "taleo": {"avoid_tables": True, "avoid_headers_footers": True, "prefer_docx": False},
        "workday": {"avoid_images": True, "prefer_docx": True, "avoid_columns": True},
        "greenhouse": {"handles_pdf_well": True, "avoid_graphics": True},
        "icims": {"avoid_text_boxes": True, "avoid_tables": True},
        "lever": {"handles_pdf_well": True, "semantic_parsing": True},
    }

    # Keywords that boost ATS scores by category
    POWER_KEYWORDS = {
        "achievement_verbs": [
            "achieved", "improved", "increased", "reduced", "implemented",
            "developed", "led", "managed", "created", "designed",
            "optimized", "automated", "streamlined", "delivered", "launched"
        ],
        "technical_skills": [
            "python", "machine learning", "deep learning", "sql", "aws",
            "docker", "kubernetes", "git", "ci/cd", "agile", "scrum"
        ],
        "soft_skills": [
            "leadership", "communication", "teamwork", "problem-solving",
            "analytical", "detail-oriented", "self-motivated", "adaptable"
        ],
        "energy_domain": [
            "renewable energy", "wind energy", "solar", "power systems",
            "grid", "energy efficiency", "smart grid", "energy storage"
        ]
    }

    def __init__(self):
        """Initialize ATS optimizer"""
        pass

    def analyze_ats_score(
        self,
        cv_text: str,
        job_description: str,
        target_ats: str = "generic"
    ) -> Dict[str, any]:
        """
        Analyze how well a CV matches job description for ATS systems.

        Returns:
            {
                "overall_score": float (0-100),
                "keyword_match": float (0-100),
                "formatting_score": float (0-100),
                "improvements": List[str],
                "matched_keywords": List[str],
                "missing_keywords": List[str],
                "ats_warnings": List[str]
            }
        """
        # Extract keywords from job description
        job_keywords = self._extract_job_keywords(job_description)

        # Extract keywords from CV
        cv_keywords = self._extract_cv_keywords(cv_text)

        # Calculate keyword match
        matched = set(job_keywords).intersection(set(cv_keywords))
        missing = set(job_keywords) - set(cv_keywords)

        keyword_match_rate = (len(matched) / len(job_keywords) * 100) if job_keywords else 0

        # Check formatting issues
        formatting_issues = self._check_formatting(cv_text, target_ats)
        formatting_score = max(0, 100 - (len(formatting_issues) * 10))

        # Calculate overall score
        overall_score = (keyword_match_rate * 0.7) + (formatting_score * 0.3)

        # Generate improvements
        improvements = self._generate_improvements(
            matched, missing, formatting_issues, job_description, cv_text
        )

        return {
            "overall_score": round(overall_score, 1),
            "keyword_match": round(keyword_match_rate, 1),
            "formatting_score": round(formatting_score, 1),
            "matched_keywords": list(matched)[:20],
            "missing_keywords": list(missing)[:15],
            "ats_warnings": formatting_issues,
            "improvements": improvements,
            "keyword_density": self._calculate_keyword_density(cv_text, matched)
        }

    def optimize_cover_letter(
        self,
        cover_letter: str,
        job_keywords: List[str],
        max_keyword_density: float = 0.03
    ) -> Tuple[str, Dict]:
        """
        Optimize cover letter for ATS by incorporating missing keywords naturally.

        Args:
            cover_letter: Original cover letter text
            job_keywords: Keywords from job description
            max_keyword_density: Maximum keyword density (default 3%)

        Returns:
            (optimized_letter, analysis_dict)
        """
        # Analyze current state
        current_keywords = self._extract_cv_keywords(cover_letter.lower())
        missing = [kw for kw in job_keywords if kw.lower() not in current_keywords]

        # Determine how many keywords to add
        word_count = len(cover_letter.split())
        max_keywords_to_add = int(word_count * max_keyword_density)
        keywords_to_add = missing[:min(max_keywords_to_add, 8)]

        analysis = {
            "original_keyword_count": len(current_keywords),
            "keywords_added": keywords_to_add,
            "final_keyword_density": len(current_keywords + keywords_to_add) / word_count if word_count > 0 else 0,
            "suggestions": [
                f"Naturally incorporate: {kw}" for kw in keywords_to_add
            ]
        }

        # Note: Actual keyword insertion should be done by LLM to maintain natural flow
        # This function returns suggestions rather than auto-inserting
        return cover_letter, analysis

    def _extract_job_keywords(self, job_description: str) -> List[str]:
        """Extract important keywords from job description"""
        text_lower = job_description.lower()

        keywords = []

        # Technical skills (usually capitalized or in lists)
        tech_pattern = r'\b[A-Z][A-Za-z0-9+#./-]+\b'
        tech_matches = re.findall(tech_pattern, job_description)
        keywords.extend([t.lower() for t in tech_matches if len(t) > 2])

        # Common job requirement phrases
        requirement_phrases = [
            "experience with", "knowledge of", "proficient in",
            "expertise in", "familiar with", "skilled in"
        ]

        for phrase in requirement_phrases:
            if phrase in text_lower:
                # Extract 1-3 words after the phrase
                pattern = rf'{phrase}\s+([\w\s,]+?)(?:\.|,|;|and|\n)'
                matches = re.findall(pattern, text_lower)
                for match in matches:
                    skills = [s.strip() for s in match.split(',')]
                    keywords.extend(skills)

        # Education keywords
        edu_keywords = ["bachelor", "master", "phd", "doctorate", "degree", "diploma"]
        for kw in edu_keywords:
            if kw in text_lower:
                keywords.append(kw)

        # Domain-specific keywords
        for category, kws in self.POWER_KEYWORDS.items():
            for kw in kws:
                if kw in text_lower:
                    keywords.append(kw)

        # Clean and deduplicate
        keywords = [kw.strip().lower() for kw in keywords if len(kw.strip()) > 2]
        return list(dict.fromkeys(keywords))  # Preserve order, remove duplicates

    def _extract_cv_keywords(self, cv_text: str) -> List[str]:
        """Extract keywords present in CV"""
        text_lower = cv_text.lower()
        keywords = []

        # Extract capitalized terms and acronyms
        pattern = r'\b[A-Z][A-Za-z0-9+#./-]+\b'
        matches = re.findall(pattern, cv_text)
        keywords.extend([m.lower() for m in matches if len(m) > 2])

        # Extract from common sections
        keywords.extend(re.findall(r'\b\w+\b', text_lower))

        # Deduplicate
        return list(dict.fromkeys(keywords))

    def _check_formatting(self, cv_text: str, target_ats: str) -> List[str]:
        """Check for common ATS formatting issues"""
        issues = []

        # Check length
        word_count = len(cv_text.split())
        if word_count > 800:
            issues.append("Document may be too long (>800 words). Consider condensing.")
        elif word_count < 200:
            issues.append("Document seems too short (<200 words).")

        # Check for special characters that confuse ATS
        problematic_chars = ['|', '•', '►', '▪', '○']
        for char in problematic_chars:
            if char in cv_text:
                issues.append(f"Contains special character '{char}' that may confuse ATS. Use standard bullet '-'")
                break

        # Check for common formatting mistakes
        if cv_text.count('\t') > 5:
            issues.append("Too many tabs. Use spaces for alignment.")

        # Warn about tables/columns (common ATS issue)
        if '|' in cv_text or cv_text.count('  ') > 20:
            issues.append("Possible table or column formatting detected. ATS may not parse correctly.")

        return issues

    def _calculate_keyword_density(self, text: str, keywords: Set[str]) -> Dict[str, float]:
        """Calculate density of matched keywords"""
        words = text.lower().split()
        total_words = len(words)

        if total_words == 0:
            return {}

        density = {}
        for kw in keywords:
            count = text.lower().count(kw.lower())
            density[kw] = round((count / total_words) * 100, 2)

        return dict(sorted(density.items(), key=lambda x: x[1], reverse=True)[:10])

    def _generate_improvements(
        self,
        matched: Set[str],
        missing: Set[str],
        formatting_issues: List[str],
        job_desc: str,
        cv_text: str
    ) -> List[str]:
        """Generate actionable improvement suggestions"""
        improvements = []

        # Keyword improvements
        if len(missing) > 0:
            top_missing = list(missing)[:5]
            improvements.append(
                f"Add these key terms to your CV: {', '.join(top_missing)}"
            )

        # Achievement verbs
        achievement_verbs = self.POWER_KEYWORDS["achievement_verbs"]
        cv_verbs = [v for v in achievement_verbs if v in cv_text.lower()]
        if len(cv_verbs) < 3:
            improvements.append(
                "Use more achievement verbs (e.g., 'achieved', 'improved', 'implemented') to describe accomplishments"
            )

        # Formatting improvements
        if formatting_issues:
            improvements.append(f"Fix formatting issues: {formatting_issues[0]}")

        # Quantification
        numbers = re.findall(r'\d+%|\d+x|\d+', cv_text)
        if len(numbers) < 3:
            improvements.append(
                "Add quantifiable achievements (e.g., 'improved efficiency by 30%', 'managed team of 5')"
            )

        return improvements[:6]  # Return top 6 improvements


# Example usage
if __name__ == "__main__":
    optimizer = ATSOptimizer()

    cv_sample = """
    Energy Engineer with Python and Machine Learning experience.
    Developed power system optimization algorithms. Led team of 3 engineers.
    MSc in Energy Engineering.
    """

    job_sample = """
    We seek a Wind Energy Engineer with expertise in Python, machine learning,
    and renewable energy systems. Experience with grid integration and power systems required.
    """

    result = optimizer.analyze_ats_score(cv_sample, job_sample)
    print(f"ATS Score: {result['overall_score']}/100")
    print(f"Matched Keywords: {result['matched_keywords'][:5]}")
    print(f"Missing Keywords: {result['missing_keywords'][:5]}")
    print(f"Improvements:\n" + "\n".join(f"  • {imp}" for imp in result['improvements']))

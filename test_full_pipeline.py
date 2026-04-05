"""
Full Pipeline Test with Real User Documents
Tests:
1. LLM client (Azure primary, OpenRouter fallback)
2. Document manager (CV, cover letters)
3. CV parsing
4. Job scoring with semantic matching
5. Cover letter style learning
"""
import asyncio
from pathlib import Path
from loguru import logger

from core.config import settings
from core.llm_client import get_llm_client
from core.document_manager import get_document_manager
from cv.cv_parser import CVParser
from matching.semantic_enhancer import SemanticEnhancer
from matching.ats_optimizer import ATSOptimizer


def test_llm_clients():
    """Test both Azure (primary) and OpenRouter (fallback)"""
    print("\n" + "="*80)
    print("TEST 1: LLM CLIENT CONFIGURATION")
    print("="*80)

    # Test primary (Azure Sweden Central)
    print("\n[1a] Testing PRIMARY LLM (Azure Sweden Central)")
    print(f"Endpoint: {settings.llm_api_base_url[:50]}...")
    print(f"Model: {settings.llm_model_name}")

    try:
        client = get_llm_client()
        print(f"Provider detected: {client.provider}")
        print(f"Model: {client.model_name}")

        # Simple test
        response = client.chat_completion(
            messages=[
                {"role": "user", "content": "Say 'Primary LLM working' in JSON format"}
            ],
            temperature=0,
            max_tokens=50
        )
        result = client.get_response_text(response)
        print(f"Response: {result[:100]}...")
        print("[OK] PRIMARY LLM WORKING")
    except Exception as e:
        print(f"[FAIL] PRIMARY LLM FAILED: {e}")

    # Test fallback (OpenRouter)
    if settings.fallback_llm_api_base_url:
        print("\n[1b] Testing FALLBACK LLM (OpenRouter)")
        print(f"Endpoint: {settings.fallback_llm_api_base_url}")
        print(f"Model: {settings.fallback_llm_model_name}")

        try:
            fallback_client = get_llm_client(
                api_base=settings.fallback_llm_api_base_url,
                api_key=settings.fallback_llm_api_key,
                model_name=settings.fallback_llm_model_name
            )
            print(f"Provider detected: {fallback_client.provider}")

            response = fallback_client.chat_completion(
                messages=[
                    {"role": "user", "content": "Say 'Fallback LLM working' in JSON format"}
                ],
                temperature=0,
                max_tokens=50
            )
            result = fallback_client.get_response_text(response)
            print(f"Response: {result[:100]}...")
            print("[OK] FALLBACK LLM WORKING")
        except Exception as e:
            print(f"[FAIL] FALLBACK LLM FAILED: {e}")


def test_document_manager():
    """Test document detection and organization"""
    print("\n" + "="*80)
    print("TEST 2: DOCUMENT MANAGER")
    print("="*80)

    doc_mgr = get_document_manager()
    summary = doc_mgr.get_summary()

    print(f"\nTotal documents found: {summary['total_documents']}")
    print(f"\nBreakdown by type:")
    for doc_type, count in summary['by_type'].items():
        print(f"  {doc_type:20s}: {count} files")

    # Check CV
    cv = doc_mgr.get_cv()
    if cv:
        print(f"\n[OK] Primary CV found:")
        print(f"   File: {cv.filename}")
        print(f"   Path: {cv.filepath}")
        print(f"   Format: {cv.file_format}")
        print(f"   Size: {cv.size_bytes / 1024:.1f} KB")
    else:
        print("\n[FAIL] No CV found!")

    # Check cover letters
    cover_letters = doc_mgr.get_cover_letters()
    print(f"\n[NOTE] Cover letter samples: {len(cover_letters)}")
    for cl in cover_letters:
        print(f"   - {cl.filename}")

    # Test document suggestions for a sample job
    print("\n" + "-"*80)
    print("Testing document suggestions for sample job:")
    sample_job = """
    PhD Position in Energy Systems
    Requirements: Master's degree in Energy Engineering or related field.
    Proof of academic excellence (transcripts required).
    Valid work permit for Germany.
    Fluent English required.
    """
    print(sample_job)

    suggestions = doc_mgr.suggest_documents_for_job(sample_job)
    print("\nDocument suggestions:")
    print(f"  Required: {len(suggestions['required'])} documents")
    print(f"  Recommended: {len(suggestions['recommended'])} documents")
    print(f"  Optional: {len(suggestions['optional'])} documents")

    # Check for missing documents
    required = ["cv", "transcript", "certificate", "residence_permit"]
    missing = doc_mgr.get_missing_documents(required)
    if missing:
        print(f"\n[WARN]  Missing documents: {', '.join(missing)}")
        for doc_type in missing:
            print(doc_mgr.ask_user_for_document(doc_type))
    else:
        print(f"\n[OK] All required documents present!")


async def test_cv_parsing():
    """Test CV parsing"""
    print("\n" + "="*80)
    print("TEST 3: CV PARSING")
    print("="*80)

    doc_mgr = get_document_manager()
    cv = doc_mgr.get_cv()

    if not cv:
        print("[FAIL] No CV found to parse")
        return

    print(f"\nParsing CV: {cv.filename}")

    try:
        parser = CVParser()
        cv_text = parser.extract_text(str(cv.filepath))
        print(f"Extracted {len(cv_text)} characters from CV")

        cv_profile = parser.parse(cv_text)

        print(f"\n[OK] CV parsed successfully!")
        print(f"\nExtracted information:")
        print(f"  Name: {cv_profile.name}")
        print(f"  Email: {cv_profile.email}")
        print(f"  Skills: {len(cv_profile.skills) if cv_profile.skills else 0}")
        if cv_profile.skills:
            if isinstance(cv_profile.skills, list):
                print(f"    - {', '.join(cv_profile.skills[:10])}")
            elif isinstance(cv_profile.skills, dict):
                for category, skills in list(cv_profile.skills.items())[:3]:
                    print(f"    {category}: {', '.join(skills[:5])}")

        print(f"  Education: {len(cv_profile.education) if cv_profile.education else 0} entries")
        if cv_profile.education:
            for edu in cv_profile.education[:2]:
                print(f"    - {edu.get('degree', 'N/A')}: {edu.get('field', 'N/A')}")

        print(f"  Experience: {len(cv_profile.experience) if cv_profile.experience else 0} entries")
        if cv_profile.experience:
            for exp in cv_profile.experience[:2]:
                print(f"    - {exp.get('title', 'N/A')} at {exp.get('company', 'N/A')}")

        return cv_profile
    except Exception as e:
        print(f"[FAIL] CV parsing failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_semantic_matching():
    """Test semantic job matching"""
    print("\n" + "="*80)
    print("TEST 4: SEMANTIC JOB MATCHING")
    print("="*80)

    enhancer = SemanticEnhancer()

    # User CV skills (typical energy engineering background)
    cv_skills = [
        "Energy Engineering",
        "Power Systems",
        "Python Programming",
        "Machine Learning",
        "Grid Optimization",
        "Renewable Energy",
        "Data Analysis"
    ]

    # Sample job: Wind Energy Engineer
    job_desc = """
    Wind Energy Systems Engineer

    We are seeking a talented engineer to join our renewable energy team.

    Responsibilities:
    - Design and optimize wind turbine systems
    - Perform power flow analysis for wind farm integration
    - Develop grid connection strategies for offshore wind
    - Use Python and ML for wind forecasting

    Requirements:
    - Background in energy engineering or electrical engineering
    - Experience with renewable energy systems
    - Proficiency in Python and data analysis
    - Understanding of power grid integration
    """

    print(f"\nCV Skills: {', '.join(cv_skills)}")
    print(f"\nJob Description:")
    print(job_desc[:300] + "...")

    result = enhancer.semantic_match_score(cv_skills, job_desc)

    print(f"\n{'='*80}")
    print("SEMANTIC MATCHING RESULTS")
    print("="*80)
    print(f"Match Score: {result['score']:.1f}/10")
    print(f"\nMatched Skills:")
    for skill in result['matched_skills'][:10]:
        print(f"  + {skill}")

    print(f"\nSemantic Relationships Found: {len(result['semantic_matches'])}")
    for cv_skill, job_req, similarity in result['semantic_matches'][:5]:
        print(f"  - '{cv_skill}' <-> '{job_req}' (similarity: {similarity:.2f})")

    if result['semantic_matches']:
        print("\n[OK] SEMANTIC MATCHING WORKING!")
    else:
        print("\n[WARN]  No semantic matches found (may need to adjust knowledge graph)")


def test_ats_optimization():
    """Test ATS scoring"""
    print("\n" + "="*80)
    print("TEST 5: ATS OPTIMIZATION")
    print("="*80)

    optimizer = ATSOptimizer()

    cv_text = """
    Energy Engineering professional with MSc degree.
    Expert in Python, Machine Learning, Power Systems, Grid Optimization.
    Experience with renewable energy systems and wind turbine design.
    Strong background in data analysis and optimization algorithms.
    """

    job_desc = """
    Wind Energy Systems Engineer
    Required: MSc in Energy Engineering, Python, Machine Learning
    Power systems analysis experience required
    """

    print(f"\nCV excerpt: {cv_text[:200]}...")
    print(f"\nJob requirements: {job_desc[:200]}...")

    result = optimizer.analyze_ats_score(cv_text, job_desc)

    print(f"\n{'='*80}")
    print("ATS ANALYSIS")
    print("="*80)
    print(f"Overall ATS Score: {result['overall_score']:.1f}/100")
    print(f"Keyword Match: {result['keyword_match']:.1f}/100")
    print(f"Formatting Score: {result['formatting_score']:.1f}/100")

    print(f"\nMatched Keywords ({len(result['matched_keywords'])}):")
    for kw in result['matched_keywords'][:10]:
        print(f"  + {kw}")

    if result['missing_keywords']:
        print(f"\nMissing Keywords ({len(result['missing_keywords'])}):")
        for kw in result['missing_keywords'][:5]:
            print(f"  X {kw}")

    if result['overall_score'] >= 70:
        print("\n[OK] STRONG ATS COMPATIBILITY!")
    elif result['overall_score'] >= 50:
        print("\n[WARN]  MODERATE ATS COMPATIBILITY")
    else:
        print("\n[FAIL] LOW ATS COMPATIBILITY - CV needs optimization")


async def main():
    """Run all tests"""
    print("\n")
    print("="*80)
    print("JOBPREDATOR FULL PIPELINE TEST")
    print("="*80)
    print(f"Testing with OpenRouter fallback enabled")
    print(f"User documents directory: {settings.documents_dir}")
    print("="*80)

    # Test 1: LLM clients
    test_llm_clients()

    # Test 2: Document manager
    test_document_manager()

    # Test 3: CV parsing
    cv_profile = await test_cv_parsing()

    # Test 4: Semantic matching
    test_semantic_matching()

    # Test 5: ATS optimization
    test_ats_optimization()

    print("\n" + "="*80)
    print("TEST SUITE COMPLETE")
    print("="*80)
    print("\nNext steps:")
    print("1. Check if all tests passed")
    print("2. Add any missing documents to user_documents/")
    print("3. Run actual job scraping: python main.py scrape -p 'Your Position'")
    print("4. Test application: python main.py apply <job_id> --dry-run")
    print("="*80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

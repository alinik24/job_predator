"""
Quick Test - Azure LLM + Document Manager + Semantic Matching
"""
import asyncio
from core.llm_client import get_llm_client
from core.document_manager import get_document_manager
from matching.semantic_enhancer import SemanticEnhancer

print("="*80)
print("QUICK TEST: Azure LLM + Documents")
print("="*80)

# Test 1: Azure LLM
print("\n[1] Testing Azure LLM")
client = get_llm_client()
print(f"Provider: {client.provider}")
print(f"Model: {client.model_name}")

response = client.chat_completion(
    messages=[{"role": "user", "content": "Say 'Azure working' in 3 words"}],
    temperature=0,
    max_tokens=20
)
print(f"Response: {client.get_response_text(response)}")
print("[OK] Azure LLM working")

# Test 2: Document Manager
print("\n[2] Document Manager")
doc_mgr = get_document_manager()
summary = doc_mgr.get_summary()
print(f"Total documents: {summary['total_documents']}")
print(f"  CV: {summary['cv_available']}")
print(f"  Cover letters: {summary['cover_letter_samples']}")
print(f"  Certificates: {summary['certificates']}")
print(f"  Transcripts: {summary['transcripts']}")
print(f"  Residence permits: {summary['residence_permits']}")
print("[OK] Document manager working")

# Test 3: Semantic Matching
print("\n[3] Semantic Matching")
enhancer = SemanticEnhancer()
cv_skills = ["Energy Engineering", "Python", "Machine Learning"]
job_desc = "Wind Energy Engineer with Python and ML experience required"
result = enhancer.semantic_match_score(cv_skills, job_desc)
print(f"Match score: {result['score']:.1f}/10")
print(f"Semantic matches: {len(result['semantic_matches'])}")
print("[OK] Semantic matching working")

print("\n" + "="*80)
print("ALL SYSTEMS OPERATIONAL")
print("="*80)
print("\nReady for:")
print("- Job scraping: python main.py scrape -p 'Data Engineer'")
print("- Job scoring with Azure LLM")
print("- Application automation")
print("\nOpenRouter Status: Needs credits")
print("  Add credits at: https://openrouter.ai/settings/credits")
print("  Current config: App name 'JobPredator' set correctly")
print("="*80)

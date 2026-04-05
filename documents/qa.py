"""
Application Q&A — RAG-powered system to answer application form questions.

When an application form asks a question (e.g., "Why do you want to work here?",
"What is your expected salary?", "Do you have a work permit for Germany?"),
this module retrieves relevant context from stored documents and generates
an accurate, personalized answer using Azure OpenAI.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger
from openai import AzureOpenAI

from core.config import settings, get_token_kwargs
from core.models import CVProfileSchema, Job
from cv.cv_parser import CVParser
from documents.store import DocumentStore

QA_SYSTEM_PROMPT = """\
You are filling out a job application form on behalf of the candidate.
Answer the question accurately and professionally based ONLY on the provided context (CV, documents, job info).

Rules:
- Answer in the same language as the question (German or English)
- Be concise but complete — form answers should be 1-3 sentences max unless it's a text area
- For salary questions: give the range from the CV or use market-appropriate values
- For yes/no questions: respond with just "Yes" or "No" (or "Ja"/"Nein" for German)
- For numeric fields: respond with just the number
- For dropdown/selection questions: respond with exactly one of the provided options
- Never invent information not present in the context
- If the answer is genuinely unknown, give a professional placeholder

CONTEXT:
{context}

JOB: {job_title} at {company}
"""


class ApplicationQA:
    """
    Answers application form questions using RAG over the user's documents and CV.
    """

    def __init__(self, cv_profile: CVProfileSchema):
        self.cv_profile = cv_profile
        self.doc_store = DocumentStore()
        self.client = AzureOpenAI(
            azure_endpoint=settings.llm_api_base_url,
            api_key=settings.llm_api_key,
            api_version=settings.llm_api_version,
        )
        self.model_name = settings.llm_model_name
        self._cv_text = CVParser().get_cv_summary_for_llm(cv_profile)

    async def answer(
        self,
        question: str,
        job: Optional[Job] = None,
        field_type: str = "text",
        options: Optional[list] = None,
    ) -> str:
        """
        Generate an answer for an application form question.

        Args:
            question: The question text from the form field
            job: The job being applied to (for context)
            field_type: 'text', 'textarea', 'number', 'boolean', 'select'
            options: For select fields, list of available options

        Returns:
            The answer string, ready to type into the form
        """
        # First check cache (already answered this question for similar jobs)
        cached = self._check_cache(question)
        if cached:
            return cached

        # Retrieve relevant documents
        relevant_docs = await self.doc_store.find_similar(question, top_k=3)
        doc_context = "\n\n---\n\n".join(
            f"[{doc.name}]\n{(doc.content_text or '')[:500]}"
            for doc in relevant_docs
        )

        # Build full context
        context = f"CV SUMMARY:\n{self._cv_text}\n\n"
        if doc_context:
            context += f"SUPPORTING DOCUMENTS:\n{doc_context}\n\n"

        # Build the prompt
        system = QA_SYSTEM_PROMPT.format(
            context=context,
            job_title=job.title if job else "the position",
            company=job.company if job else "the company",
        )

        # Augment question for specific field types
        user_question = question
        if field_type == "boolean":
            user_question = f"Answer only Yes or No: {question}"
        elif field_type == "number":
            user_question = f"Answer only with a number: {question}"
        elif field_type == "select" and options:
            opts_str = ", ".join(f'"{o}"' for o in options)
            user_question = f"Choose exactly one option from [{opts_str}]: {question}"

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_question},
                ],
                temperature=0.1,
                **get_token_kwargs(self.model_name, 256),
            )
            answer = response.choices[0].message.content.strip()
            logger.info(f"[QA] Q: '{question[:60]}...' → A: '{answer[:80]}'")
            return answer

        except Exception as e:
            logger.error(f"[QA] Error answering '{question}': {e}")
            return self._fallback_answer(question, field_type)

    def _check_cache(self, question: str) -> Optional[str]:
        """Simple keyword-based cache for common questions."""
        q_lower = question.lower()
        cv = self.cv_profile

        # Salary
        if any(kw in q_lower for kw in ["salary", "gehalt", "compensation", "vergütung"]):
            return "65000 - 80000"

        # Work authorization / visa
        if any(kw in q_lower for kw in ["work permit", "arbeitserlaubnis", "visa", "authorized"]):
            return "Yes"

        # Remote / relocation
        if "relocat" in q_lower or "umzug" in q_lower:
            return "Yes, I am open to relocation"

        # Notice period / Kündigungsfrist
        if any(kw in q_lower for kw in ["notice", "kündigungsfrist", "start date", "startdatum"]):
            return "4 weeks / 1 month"

        # LinkedIn / GitHub
        if "linkedin" in q_lower and cv.linkedin_url:
            return cv.linkedin_url
        if "github" in q_lower and cv.github_url:
            return cv.github_url

        # Phone
        if "phone" in q_lower or "telefon" in q_lower:
            return cv.phone or ""

        # Email
        if "email" in q_lower or "e-mail" in q_lower:
            return cv.email or ""

        return None

    def _fallback_answer(self, question: str, field_type: str) -> str:
        """Return a safe fallback when LLM call fails."""
        if field_type == "boolean":
            return "Yes"
        if field_type == "number":
            return "0"
        if field_type == "select":
            return ""
        return "Please see my attached CV for details."

    async def build_full_form_answers(
        self,
        questions: list[dict],
        job: Optional[Job] = None,
    ) -> dict[str, str]:
        """
        Answer a list of form questions in batch.

        Args:
            questions: List of dicts with keys: question, field_type, options (optional)
            job: The job being applied to

        Returns:
            Dict mapping question → answer
        """
        answers = {}
        for q in questions:
            question_text = q.get("question", "")
            field_type = q.get("field_type", "text")
            options = q.get("options")

            if not question_text:
                continue

            answer = await self.answer(question_text, job, field_type, options)
            answers[question_text] = answer

        return answers

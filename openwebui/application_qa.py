"""
Application Q&A System - Answer job application questions using Hybrid RAG

Uses hybrid retrieval (Sismics + Vector + Knowledge Graph) to find relevant
information from user's documents and generates accurate, personalized answers.

Common application questions:
- "Why do you want to work at [company]?"
- "What are your salary expectations?"
- "Do you have work authorization in Germany?"
- "Tell us about your Python experience"
- "What is your availability?"
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from loguru import logger

from openwebui.hybrid_rag import HybridRAG
from config.model_config import get_llm_client, get_model_config


class ApplicationQA:
    """
    Answers job application form questions using hybrid RAG

    Usage:
        qa = ApplicationQA()
        await qa.initialize()
        answer = await qa.answer(
            question="What Python projects have you worked on?",
            job_title="Python Developer",
            company="Google"
        )
    """

    # System prompt for answering application questions
    SYSTEM_PROMPT = """You are helping a user fill out a job application form.

Your task:
- Answer questions accurately based ONLY on the provided context from the user's documents
- Be professional and concise
- Match the tone and language of the question
- For yes/no questions, answer with just "Yes" or "No"
- For numeric questions, provide just the number
- Never invent information not in the context
- If information is missing, give a professional placeholder like "Please specify" or "To be discussed"

Answer the question directly without preamble."""

    # Question type detection patterns
    QUESTION_PATTERNS = {
        'salary': ['salary', 'gehalt', 'compensation', 'vergütung', 'expected salary'],
        'availability': ['availability', 'verfügbarkeit', 'start date', 'startdatum', 'when can you start'],
        'work_permit': ['work permit', 'work authorization', 'arbeitserlaubnis', 'aufenthaltserlaubnis', 'visa'],
        'motivation': ['why', 'warum', 'interest', 'interesse', 'motivation'],
        'experience': ['experience', 'erfahrung', 'background', 'worked', 'gearbeitet'],
        'skills': ['skills', 'fähigkeiten', 'technologies', 'tools', 'programming'],
        'education': ['education', 'ausbildung', 'degree', 'university', 'universität', 'studied'],
        'yes_no': ['do you have', 'haben sie', 'are you', 'sind sie', 'can you', 'können sie']
    }

    def __init__(
        self,
        # Hybrid RAG configuration
        use_sismics: bool = True,
        sismics_url: str = "http://localhost:8080",
        sismics_username: str = "admin",
        sismics_password: str = "admin",
        vector_db_dir: str = "vector_db",
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "jobpredator123",

        # LLM configuration
        temperature: float = 0.2,  # Low temperature for factual answers
        max_tokens: int = 500
    ):
        """
        Args:
            use_sismics: Enable Sismics integration
            sismics_url: Sismics server URL
            sismics_username: Sismics username
            sismics_password: Sismics password
            vector_db_dir: ChromaDB directory
            neo4j_uri: Neo4j connection
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            temperature: LLM temperature (0-1, lower = more factual)
            max_tokens: Max tokens in response
        """
        # Initialize hybrid RAG
        self.rag = HybridRAG(
            use_sismics=use_sismics,
            sismics_url=sismics_url,
            sismics_username=sismics_username,
            sismics_password=sismics_password,
            vector_db_dir=vector_db_dir,
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password
        )

        # Initialize LLM
        self.config = get_model_config()
        self.client = get_llm_client()
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.initialized = False
        logger.info("ApplicationQA initialized")

    async def initialize(self):
        """Initialize connections"""
        await self.rag.initialize()
        self.initialized = True
        logger.info("✓ ApplicationQA ready")

    async def answer(
        self,
        question: str,
        job_title: Optional[str] = None,
        company: Optional[str] = None,
        field_type: str = "text",
        options: Optional[list] = None,
        context_override: Optional[str] = None
    ) -> str:
        """
        Generate answer for an application form question

        Args:
            question: The question from the application form
            job_title: Job position being applied for
            company: Company name
            field_type: Form field type ('text', 'textarea', 'number', 'boolean', 'select')
            options: For select fields, list of options to choose from
            context_override: Optional manual context (skip retrieval)

        Returns:
            Answer string ready to paste into form
        """
        if not self.initialized:
            await self.initialize()

        logger.info(f"Answering question: '{question[:100]}...'")

        # Detect question type
        question_type = self._detect_question_type(question)
        logger.info(f"  Type: {question_type}")

        # Get relevant context from documents
        if context_override:
            context = context_override
        else:
            context = await self._get_context_for_question(question, question_type)

        # Build prompt
        user_prompt = self._build_prompt(
            question=question,
            context=context,
            job_title=job_title,
            company=company,
            field_type=field_type,
            options=options,
            question_type=question_type
        )

        # Generate answer
        try:
            response = self.client.chat.completions.create(
                model=self.config.llm_model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )

            answer = response.choices[0].message.content.strip()
            logger.info(f"  Answer: {answer[:100]}...")

            return answer

        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return self._get_fallback_answer(question, question_type)

    async def _get_context_for_question(self, question: str, question_type: str) -> str:
        """
        Retrieve relevant context based on question type

        Uses different retrieval strategies for different question types
        """
        # Adjust retrieval based on question type
        if question_type == 'skills':
            # For skills questions, emphasize vector + graph (better for technical terms)
            results = await self.rag.retrieve(
                question,
                top_k=8,
                enable_sismics=False,  # Skills are better found via embeddings
                enable_vector=True,
                enable_graph=True
            )
        elif question_type == 'experience':
            # For experience, use all sources
            results = await self.rag.retrieve(
                question,
                top_k=10,
                enable_sismics=True,
                enable_vector=True,
                enable_graph=True
            )
        elif question_type == 'education':
            # For education, prefer knowledge graph (structured data)
            results = await self.rag.retrieve(
                question,
                top_k=6,
                enable_sismics=True,
                enable_vector=False,
                enable_graph=True
            )
        else:
            # Default: use all sources
            results = await self.rag.retrieve(question, top_k=8)

        # Format results as context
        if not results:
            return "No relevant information found in user's documents."

        context_parts = []
        for idx, result in enumerate(results[:5], 1):  # Top 5 for context
            content = result.content[:400] if result.content else ""
            context_parts.append(f"[{idx}] {content}")

        return "\n\n".join(context_parts)

    def _build_prompt(
        self,
        question: str,
        context: str,
        job_title: Optional[str],
        company: Optional[str],
        field_type: str,
        options: Optional[list],
        question_type: str
    ) -> str:
        """Build LLM prompt for answering the question"""
        prompt_parts = []

        # Job context
        if job_title or company:
            job_info = []
            if company:
                job_info.append(f"Company: {company}")
            if job_title:
                job_info.append(f"Position: {job_title}")
            prompt_parts.append("JOB CONTEXT:\n" + "\n".join(job_info))

        # Retrieved context
        prompt_parts.append(f"CANDIDATE'S INFORMATION (from documents):\n{context}")

        # Question
        prompt_parts.append(f"QUESTION:\n{question}")

        # Field type hints
        if field_type == "boolean" or question_type == "yes_no":
            prompt_parts.append("\nIMPORTANT: This is a yes/no question. Answer with ONLY 'Yes' or 'No' (or 'Ja'/'Nein' if question is in German).")
        elif field_type == "number":
            prompt_parts.append("\nIMPORTANT: This is a numeric field. Answer with ONLY a number.")
        elif field_type == "select" and options:
            prompt_parts.append(f"\nIMPORTANT: This is a dropdown field. Choose EXACTLY ONE from: {', '.join(options)}")
        elif field_type == "textarea":
            prompt_parts.append("\nNote: This is a text area field. You can provide a longer answer (2-4 sentences).")
        else:
            prompt_parts.append("\nNote: Keep answer concise (1-2 sentences).")

        return "\n\n".join(prompt_parts)

    def _detect_question_type(self, question: str) -> str:
        """Detect question type based on keywords"""
        question_lower = question.lower()

        for q_type, patterns in self.QUESTION_PATTERNS.items():
            if any(pattern in question_lower for pattern in patterns):
                return q_type

        return 'general'

    def _get_fallback_answer(self, question: str, question_type: str) -> str:
        """Provide fallback answer when generation fails"""
        fallbacks = {
            'salary': 'Competitive salary based on experience',
            'availability': 'Available to start immediately',
            'work_permit': 'Yes',
            'yes_no': 'Yes',
            'general': 'Please refer to CV for details'
        }

        return fallbacks.get(question_type, fallbacks['general'])

    async def batch_answer(
        self,
        questions: list[Dict[str, Any]],
        job_title: Optional[str] = None,
        company: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Answer multiple questions at once (more efficient)

        Args:
            questions: List of question dicts with keys: 'question', 'field_type', 'options'
            job_title: Job title
            company: Company name

        Returns:
            Dict mapping question -> answer
        """
        if not self.initialized:
            await self.initialize()

        answers = {}

        for q_info in questions:
            question = q_info.get('question', '')
            if not question:
                continue

            try:
                answer = await self.answer(
                    question=question,
                    job_title=job_title,
                    company=company,
                    field_type=q_info.get('field_type', 'text'),
                    options=q_info.get('options')
                )
                answers[question] = answer

            except Exception as e:
                logger.error(f"Failed to answer '{question}': {e}")
                answers[question] = "Error generating answer"

        return answers

    async def close(self):
        """Close connections"""
        await self.rag.close()


# Convenience function
async def quick_answer(
    question: str,
    job_title: Optional[str] = None,
    company: Optional[str] = None
) -> str:
    """
    Quick answer function (one-shot, no persistent connection)

    Args:
        question: Application question
        job_title: Job title
        company: Company name

    Returns:
        Answer string
    """
    qa = ApplicationQA()
    try:
        await qa.initialize()
        return await qa.answer(question, job_title=job_title, company=company)
    finally:
        await qa.close()

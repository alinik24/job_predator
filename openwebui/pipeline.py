"""
Open WebUI Pipeline - Job Application Assistant with Hybrid RAG

This pipeline integrates with Open WebUI to provide:
- Hybrid RAG retrieval (Sismics + Vector + Knowledge Graph)
- Application question answering
- Job application assistance

Installation in Open WebUI:
1. Go to Settings > Pipelines
2. Click "Add Pipeline"
3. Upload this file or paste the URL
4. Configure valves (API keys, database connections)

Open WebUI Pipeline Specification:
https://github.com/open-webui/pipelines
"""

from typing import List, Union, Generator, Iterator, Optional
from pydantic import BaseModel
import asyncio
from loguru import logger


class Pipeline:
    """
    Open WebUI Pipeline for Job Application Assistant

    This pipeline uses hybrid RAG to answer questions about the user's
    career history, skills, and experience based on their uploaded documents.
    """

    class Valves(BaseModel):
        """
        Configuration for the pipeline

        Users can configure these in Open WebUI settings
        """
        # Sismics configuration
        USE_SISMICS: bool = True
        SISMICS_URL: str = "http://localhost:8080"
        SISMICS_USERNAME: str = "admin"
        SISMICS_PASSWORD: str = "admin"

        # Vector database
        VECTOR_DB_DIR: str = "vector_db"

        # Neo4j knowledge graph
        NEO4J_URI: str = "bolt://localhost:7687"
        NEO4J_USER: str = "neo4j"
        NEO4J_PASSWORD: str = "jobpredator123"

        # Retrieval settings
        TOP_K: int = 5
        MAX_CONTEXT_CHARS: int = 4000

        # LLM settings
        TEMPERATURE: float = 0.2
        MAX_TOKENS: int = 500

        # Feature flags
        ENABLE_SISMICS: bool = True
        ENABLE_VECTOR: bool = True
        ENABLE_GRAPH: bool = True

    def __init__(self):
        self.type = "manifold"  # Can handle multiple models
        self.id = "job_application_assistant"
        self.name = "Job Application Assistant"
        self.valves = self.Valves()

        # Will be initialized on first use
        self.rag = None
        self.qa = None
        self.initialized = False

    async def _initialize(self):
        """Lazy initialization of RAG and QA systems"""
        if self.initialized:
            return

        try:
            # Import here to avoid loading dependencies if pipeline is not used
            from openwebui.hybrid_rag import HybridRAG
            from openwebui.application_qa import ApplicationQA

            # Initialize hybrid RAG
            self.rag = HybridRAG(
                use_sismics=self.valves.USE_SISMICS,
                sismics_url=self.valves.SISMICS_URL,
                sismics_username=self.valves.SISMICS_USERNAME,
                sismics_password=self.valves.SISMICS_PASSWORD,
                vector_db_dir=self.valves.VECTOR_DB_DIR,
                neo4j_uri=self.valves.NEO4J_URI,
                neo4j_user=self.valves.NEO4J_USER,
                neo4j_password=self.valves.NEO4J_PASSWORD
            )
            await self.rag.initialize()

            # Initialize QA system
            self.qa = ApplicationQA(
                use_sismics=self.valves.USE_SISMICS,
                sismics_url=self.valves.SISMICS_URL,
                sismics_username=self.valves.SISMICS_USERNAME,
                sismics_password=self.valves.SISMICS_PASSWORD,
                vector_db_dir=self.valves.VECTOR_DB_DIR,
                neo4j_uri=self.valves.NEO4J_URI,
                neo4j_user=self.valves.NEO4J_USER,
                neo4j_password=self.valves.NEO4J_PASSWORD,
                temperature=self.valves.TEMPERATURE,
                max_tokens=self.valves.MAX_TOKENS
            )
            await self.qa.initialize()

            self.initialized = True
            logger.info("✓ Job Application Assistant pipeline ready")

        except Exception as e:
            logger.error(f"Pipeline initialization failed: {e}")
            raise

    def pipes(self) -> List[dict]:
        """
        Define available pipes (models) in this pipeline

        Open WebUI will show these as model options
        """
        return [
            {
                "id": "job_app_qa",
                "name": "Job Application Q&A",
                "description": "Answer job application questions using your documents"
            },
            {
                "id": "job_app_search",
                "name": "Document Search",
                "description": "Search through your career documents"
            }
        ]

    async def pipe(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__=None
    ) -> Union[str, Generator, Iterator]:
        """
        Main pipeline execution

        Args:
            body: Request body from Open WebUI containing messages
            __user__: User information from Open WebUI
            __event_emitter__: Event emitter for streaming responses

        Returns:
            Response string or generator for streaming
        """
        # Initialize if needed
        if not self.initialized:
            await self._initialize()

        # Extract messages
        messages = body.get("messages", [])
        if not messages:
            return "No messages provided"

        # Get the user's last message
        user_message = messages[-1].get("content", "")

        # Get model selection
        model_id = body.get("model", "job_app_qa")

        try:
            if model_id == "job_app_search":
                # Document search mode
                response = await self._handle_search(user_message)
            else:
                # Q&A mode (default)
                response = await self._handle_qa(user_message, messages)

            return response

        except Exception as e:
            logger.error(f"Pipeline execution error: {e}")
            return f"Error: {str(e)}"

    async def _handle_qa(self, question: str, messages: list) -> str:
        """
        Handle Q&A mode - answer application questions

        Detects if user is asking about job applications and provides answers
        """
        # Check if this looks like an application question
        app_keywords = [
            'application', 'apply', 'job', 'position', 'company',
            'salary', 'experience', 'skills', 'why do you',
            'tell us about', 'what is your', 'do you have'
        ]

        is_app_question = any(kw in question.lower() for kw in app_keywords)

        if is_app_question:
            # Extract job context from conversation if available
            job_title, company = self._extract_job_context(messages)

            # Use QA system to answer
            answer = await self.qa.answer(
                question=question,
                job_title=job_title,
                company=company
            )

            # Add context indicator
            response = f"**[Based on your documents]**\n\n{answer}"

        else:
            # General question - use retrieval
            context = await self.rag.get_context(
                query=question,
                top_k=self.valves.TOP_K,
                max_chars=self.valves.MAX_CONTEXT_CHARS
            )

            response = f"**[Retrieved from your documents]**\n\n{context}"

        return response

    async def _handle_search(self, query: str) -> str:
        """
        Handle search mode - retrieve relevant documents

        Returns formatted search results
        """
        results = await self.rag.retrieve(
            query,
            top_k=self.valves.TOP_K,
            enable_sismics=self.valves.ENABLE_SISMICS,
            enable_vector=self.valves.ENABLE_VECTOR,
            enable_graph=self.valves.ENABLE_GRAPH
        )

        if not results:
            return "No results found in your documents."

        # Format results
        response_parts = [f"**Found {len(results)} results:**\n"]

        for idx, result in enumerate(results, 1):
            source_emoji = {
                'sismics': '📄',
                'vector': '🔍',
                'graph': '🧠'
            }.get(result.source, '📌')

            title = result.metadata.get('title') or result.metadata.get('filename') or 'Untitled'
            content_preview = result.content[:200] if result.content else "(No preview)"

            response_parts.append(
                f"{idx}. {source_emoji} **{title}**\n"
                f"   {content_preview}...\n"
                f"   *Source: {result.source}, Score: {result.score:.3f}*\n"
            )

        return "\n".join(response_parts)

    def _extract_job_context(self, messages: list) -> tuple[Optional[str], Optional[str]]:
        """
        Extract job title and company from conversation history

        Looks for mentions of company names and job titles in recent messages
        """
        job_title = None
        company = None

        # Check last few messages for context
        recent_messages = messages[-5:] if len(messages) >= 5 else messages

        for msg in recent_messages:
            content = msg.get("content", "").lower()

            # Simple heuristics (can be improved with NER)
            if "at " in content or "for " in content:
                # Extract potential company names
                words = content.split()
                for i, word in enumerate(words):
                    if word in ["at", "for", "with"] and i + 1 < len(words):
                        potential_company = words[i + 1].strip(".,!?")
                        if potential_company[0].isupper():
                            company = potential_company.capitalize()
                            break

            # Look for job titles
            job_keywords = ["position", "role", "job", "as a", "as an"]
            for keyword in job_keywords:
                if keyword in content:
                    idx = content.find(keyword)
                    after_keyword = content[idx + len(keyword):idx + len(keyword) + 50]
                    # Extract words after keyword
                    words = after_keyword.strip().split()[:3]
                    if words:
                        job_title = " ".join(words).strip(".,!?")
                        break

        return job_title, company


# Additional utility functions that can be exposed as Open WebUI tools

async def get_user_profile():
    """
    Fetch complete user profile from knowledge graph

    Can be exposed as an Open WebUI function/tool
    """
    from ingestion.graph_builder import KnowledgeGraphBuilder

    graph = KnowledgeGraphBuilder()
    try:
        profile = await graph.get_user_profile()
        return profile
    finally:
        await graph.close()


async def search_documents(query: str, top_k: int = 5):
    """
    Search through documents

    Can be exposed as an Open WebUI function/tool
    """
    from openwebui.hybrid_rag import hybrid_retrieve

    results = await hybrid_retrieve(query, top_k=top_k, return_context=False)

    formatted_results = []
    for r in results:
        formatted_results.append({
            'content': r.content[:300],
            'source': r.source,
            'score': r.score,
            'metadata': r.metadata
        })

    return formatted_results

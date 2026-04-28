"""
Open WebUI Functions - Callable tools from chat interface

These functions can be called by Open WebUI as tools/actions:
- answer_application_question()
- search_my_documents()
- get_my_profile()
- get_my_skills()
- generate_cover_letter()

Installation in Open WebUI:
1. Go to Workspace > Functions
2. Import this file
3. Functions will be available in chat via function calling
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import asyncio


class AnswerApplicationQuestionFunction:
    """
    Function to answer job application questions

    Usage in chat:
    "Answer this application question: What is your Python experience?"
    "Help me answer: Do you have work authorization in Germany?"
    """

    class Valves(BaseModel):
        # Configuration
        USE_SISMICS: bool = Field(default=True, description="Use Sismics for document retrieval")
        SISMICS_URL: str = Field(default="http://localhost:8080", description="Sismics server URL")
        SISMICS_USERNAME: str = Field(default="admin", description="Sismics username")
        SISMICS_PASSWORD: str = Field(default="admin", description="Sismics password")
        VECTOR_DB_DIR: str = Field(default="vector_db", description="Vector database directory")
        NEO4J_URI: str = Field(default="bolt://localhost:7687", description="Neo4j connection URI")
        NEO4J_USER: str = Field(default="neo4j", description="Neo4j username")
        NEO4J_PASSWORD: str = Field(default="jobpredator123", description="Neo4j password")

    def __init__(self):
        self.valves = self.Valves()
        self.qa_system = None

    async def _get_qa_system(self):
        """Lazy initialization of QA system"""
        if self.qa_system is None:
            from openwebui.application_qa import ApplicationQA

            self.qa_system = ApplicationQA(
                use_sismics=self.valves.USE_SISMICS,
                sismics_url=self.valves.SISMICS_URL,
                sismics_username=self.valves.SISMICS_USERNAME,
                sismics_password=self.valves.SISMICS_PASSWORD,
                vector_db_dir=self.valves.VECTOR_DB_DIR,
                neo4j_uri=self.valves.NEO4J_URI,
                neo4j_user=self.valves.NEO4J_USER,
                neo4j_password=self.valves.NEO4J_PASSWORD
            )
            await self.qa_system.initialize()

        return self.qa_system

    async def __call__(
        self,
        question: str,
        job_title: Optional[str] = None,
        company: Optional[str] = None,
        __user__: Optional[dict] = None
    ) -> str:
        """
        Answer a job application question

        Args:
            question: The application question to answer
            job_title: Optional job title for context
            company: Optional company name for context
            __user__: User information from Open WebUI

        Returns:
            Answer to the question based on user's documents
        """
        qa = await self._get_qa_system()

        answer = await qa.answer(
            question=question,
            job_title=job_title,
            company=company
        )

        # Format response
        response = f"**Answer:**\n{answer}"

        if job_title or company:
            context_parts = []
            if company:
                context_parts.append(f"Company: {company}")
            if job_title:
                context_parts.append(f"Position: {job_title}")
            response = f"*Context: {', '.join(context_parts)}*\n\n" + response

        return response


class SearchDocumentsFunction:
    """
    Function to search through user's documents

    Usage in chat:
    "Search my documents for Python projects"
    "Find information about my work at Google"
    """

    class Valves(BaseModel):
        USE_SISMICS: bool = Field(default=True)
        SISMICS_URL: str = Field(default="http://localhost:8080")
        SISMICS_USERNAME: str = Field(default="admin")
        SISMICS_PASSWORD: str = Field(default="admin")
        VECTOR_DB_DIR: str = Field(default="vector_db")
        NEO4J_URI: str = Field(default="bolt://localhost:7687")
        NEO4J_USER: str = Field(default="neo4j")
        NEO4J_PASSWORD: str = Field(default="jobpredator123")
        TOP_K: int = Field(default=5, description="Number of results to return")

    def __init__(self):
        self.valves = self.Valves()
        self.rag = None

    async def _get_rag(self):
        """Lazy initialization of RAG system"""
        if self.rag is None:
            from openwebui.hybrid_rag import HybridRAG

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

        return self.rag

    async def __call__(
        self,
        query: str,
        top_k: Optional[int] = None,
        __user__: Optional[dict] = None
    ) -> str:
        """
        Search through documents

        Args:
            query: Search query
            top_k: Number of results (default from valves)
            __user__: User information from Open WebUI

        Returns:
            Formatted search results
        """
        rag = await self._get_rag()
        top_k = top_k or self.valves.TOP_K

        results = await rag.retrieve(query, top_k=top_k)

        if not results:
            return "No results found in your documents."

        # Format results
        response_parts = [f"**Found {len(results)} results for '{query}':**\n"]

        for idx, result in enumerate(results, 1):
            source_labels = {
                'sismics': 'Sismics (Full-Text)',
                'vector': 'Vector (Semantic)',
                'graph': 'Knowledge Graph'
            }
            source_label = source_labels.get(result.source, result.source)

            title = result.metadata.get('title') or result.metadata.get('filename') or 'Untitled'
            content_preview = result.content[:250] if result.content else "(No content)"

            response_parts.append(
                f"**{idx}. {title}** _{source_label}_\n"
                f"{content_preview}...\n"
                f"*Score: {result.score:.3f}*\n"
            )

        return "\n".join(response_parts)


class GetProfileFunction:
    """
    Function to get user's complete profile from knowledge graph

    Usage in chat:
    "Get my profile"
    "Show me my skills and experience"
    """

    class Valves(BaseModel):
        NEO4J_URI: str = Field(default="bolt://localhost:7687")
        NEO4J_USER: str = Field(default="neo4j")
        NEO4J_PASSWORD: str = Field(default="jobpredator123")

    def __init__(self):
        self.valves = self.Valves()

    async def __call__(
        self,
        __user__: Optional[dict] = None
    ) -> str:
        """
        Get complete user profile from knowledge graph

        Returns:
            Formatted profile with skills, experience, education
        """
        from ingestion.graph_builder import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            neo4j_uri=self.valves.NEO4J_URI,
            neo4j_user=self.valves.NEO4J_USER,
            neo4j_password=self.valves.NEO4J_PASSWORD
        )

        try:
            profile = await graph.get_user_profile()

            # Format profile
            response_parts = ["**Your Profile:**\n"]

            if profile.get('skills'):
                response_parts.append(f"**Skills ({len(profile['skills'])} total):**")
                for skill in profile['skills'][:10]:  # Show first 10
                    response_parts.append(f"  • {skill}")
                if len(profile['skills']) > 10:
                    response_parts.append(f"  ... and {len(profile['skills']) - 10} more")
                response_parts.append("")

            if profile.get('experience'):
                response_parts.append(f"**Experience ({len(profile['experience'])} items):**")
                for exp in profile['experience'][:5]:  # Show first 5
                    response_parts.append(f"  • {exp}")
                if len(profile['experience']) > 5:
                    response_parts.append(f"  ... and {len(profile['experience']) - 5} more")
                response_parts.append("")

            if profile.get('education'):
                response_parts.append(f"**Education ({len(profile['education'])} items):**")
                for edu in profile['education'][:5]:
                    response_parts.append(f"  • {edu}")
                response_parts.append("")

            if profile.get('languages'):
                response_parts.append(f"**Languages:**")
                for lang in profile['languages'][:5]:
                    response_parts.append(f"  • {lang}")
                response_parts.append("")

            return "\n".join(response_parts)

        finally:
            await graph.close()


class GetSkillsFunction:
    """
    Function to get user's technical skills

    Usage in chat:
    "What are my skills?"
    "List my programming languages"
    """

    class Valves(BaseModel):
        NEO4J_URI: str = Field(default="bolt://localhost:7687")
        NEO4J_USER: str = Field(default="neo4j")
        NEO4J_PASSWORD: str = Field(default="jobpredator123")

    def __init__(self):
        self.valves = self.Valves()

    async def __call__(
        self,
        category: Optional[str] = None,
        __user__: Optional[dict] = None
    ) -> str:
        """
        Get user's skills

        Args:
            category: Optional category filter (e.g., 'programming', 'tools')
            __user__: User information from Open WebUI

        Returns:
            List of skills
        """
        from ingestion.graph_builder import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            neo4j_uri=self.valves.NEO4J_URI,
            neo4j_user=self.valves.NEO4J_USER,
            neo4j_password=self.valves.NEO4J_PASSWORD
        )

        try:
            # Query for skills
            query = "What technical skills, programming languages, and tools does the user know?"
            if category:
                query = f"What {category} skills does the user have?"

            results = await graph.query(query, num_results=50)

            if not results:
                return "No skills found in your profile."

            # Extract unique skills
            skills = []
            for r in results:
                fact = r.fact if hasattr(r, 'fact') else str(r)
                # Extract skill names from facts
                skills.append(fact)

            # Format response
            response = f"**Your Skills ({len(skills)} found):**\n\n"
            for idx, skill in enumerate(skills[:30], 1):  # Show first 30
                response += f"{idx}. {skill}\n"

            if len(skills) > 30:
                response += f"\n... and {len(skills) - 30} more"

            return response

        finally:
            await graph.close()


# Export functions for Open WebUI
functions = [
    AnswerApplicationQuestionFunction,
    SearchDocumentsFunction,
    GetProfileFunction,
    GetSkillsFunction
]

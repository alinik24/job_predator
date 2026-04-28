"""
Hybrid RAG System - Combines Sismics + Vector Store + Knowledge Graph

Retrieval strategy:
1. Sismics full-text search (keyword matching)
2. Vector semantic search (ChromaDB)
3. Knowledge graph queries (Neo4j + Graphiti)
4. Fusion ranking (RRF - Reciprocal Rank Fusion)

Returns best results from all sources for maximum relevance.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from loguru import logger

from ingestion.sismics_client import SismicsClient, SismicsDocument
from ingestion.vector_store import VectorStore, SearchResult
from ingestion.graph_builder import KnowledgeGraphBuilder


@dataclass
class RetrievalResult:
    """Unified result from hybrid retrieval"""
    content: str
    source: str  # 'sismics', 'vector', or 'graph'
    metadata: Dict[str, Any]
    score: float  # Normalized score 0-1
    doc_id: Optional[str] = None


class HybridRAG:
    """
    Hybrid RAG system combining three retrieval methods

    Usage:
        rag = HybridRAG()
        await rag.initialize()
        results = await rag.retrieve("What Python projects did I work on?", top_k=5)
    """

    def __init__(
        self,
        # Sismics configuration
        use_sismics: bool = True,
        sismics_url: str = "http://localhost:8080",
        sismics_username: str = "admin",
        sismics_password: str = "admin",

        # Vector store configuration
        vector_db_dir: str = "vector_db",

        # Knowledge graph configuration
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "jobpredator123",

        # Retrieval weights (for fusion)
        sismics_weight: float = 0.3,
        vector_weight: float = 0.4,
        graph_weight: float = 0.3
    ):
        """
        Args:
            use_sismics: Enable Sismics full-text search
            sismics_url: Sismics server URL
            sismics_username: Sismics username
            sismics_password: Sismics password
            vector_db_dir: ChromaDB directory
            neo4j_uri: Neo4j connection string
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            sismics_weight: Weight for Sismics results (0-1)
            vector_weight: Weight for vector results (0-1)
            graph_weight: Weight for graph results (0-1)
        """
        self.use_sismics = use_sismics
        self.sismics_weight = sismics_weight
        self.vector_weight = vector_weight
        self.graph_weight = graph_weight

        # Initialize clients
        if use_sismics:
            self.sismics = SismicsClient(sismics_url, sismics_username, sismics_password)
        else:
            self.sismics = None

        self.vector_store = VectorStore(persist_directory=vector_db_dir)
        self.graph_builder = KnowledgeGraphBuilder(neo4j_uri, neo4j_user, neo4j_password)

        self.initialized = False
        logger.info(f"Hybrid RAG initialized (weights: Sismics={sismics_weight}, Vector={vector_weight}, Graph={graph_weight})")

    async def initialize(self):
        """Initialize connections (authenticate with Sismics if needed)"""
        if self.use_sismics and self.sismics:
            try:
                await self.sismics.login()
                logger.info("✓ Sismics authenticated")
            except Exception as e:
                logger.error(f"Sismics authentication failed: {e}")
                logger.warning("Continuing without Sismics (vector + graph only)")
                self.use_sismics = False

        self.initialized = True
        logger.info("✓ Hybrid RAG ready")

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        enable_sismics: bool = True,
        enable_vector: bool = True,
        enable_graph: bool = True,
        rerank: bool = True
    ) -> List[RetrievalResult]:
        """
        Retrieve relevant documents using hybrid approach

        Args:
            query: Search query
            top_k: Number of results to return
            enable_sismics: Use Sismics full-text search
            enable_vector: Use vector semantic search
            enable_graph: Use knowledge graph queries
            rerank: Apply RRF fusion ranking

        Returns:
            List of RetrievalResult ordered by relevance
        """
        if not self.initialized:
            await self.initialize()

        logger.info(f"Hybrid retrieval: '{query}' (top_k={top_k})")

        all_results: List[RetrievalResult] = []

        # 1. Sismics full-text search
        if enable_sismics and self.use_sismics:
            try:
                sismics_results = await self._retrieve_sismics(query, limit=top_k)
                all_results.extend(sismics_results)
                logger.info(f"  Sismics: {len(sismics_results)} results")
            except Exception as e:
                logger.error(f"Sismics retrieval failed: {e}")

        # 2. Vector semantic search
        if enable_vector:
            try:
                vector_results = self._retrieve_vector(query, n_results=top_k)
                all_results.extend(vector_results)
                logger.info(f"  Vector: {len(vector_results)} results")
            except Exception as e:
                logger.error(f"Vector retrieval failed: {e}")

        # 3. Knowledge graph queries
        if enable_graph:
            try:
                graph_results = await self._retrieve_graph(query, num_results=top_k)
                all_results.extend(graph_results)
                logger.info(f"  Graph: {len(graph_results)} results")
            except Exception as e:
                logger.error(f"Graph retrieval failed: {e}")

        # 4. Fusion ranking (RRF)
        if rerank and len(all_results) > 0:
            ranked_results = self._reciprocal_rank_fusion(all_results, top_k)
        else:
            # Just sort by score and take top_k
            ranked_results = sorted(all_results, key=lambda x: x.score, reverse=True)[:top_k]

        logger.info(f"✓ Retrieved {len(ranked_results)} results after fusion")
        return ranked_results

    async def _retrieve_sismics(self, query: str, limit: int) -> List[RetrievalResult]:
        """Retrieve from Sismics full-text search"""
        if not self.sismics:
            return []

        sismics_docs = await self.sismics.search_documents(query, limit=limit)

        results = []
        for idx, doc in enumerate(sismics_docs):
            # Sismics doesn't give scores, use position as proxy (1/rank)
            score = 1.0 / (idx + 1)

            results.append(RetrievalResult(
                content=doc.content if doc.content else doc.description,
                source='sismics',
                metadata={
                    'title': doc.title,
                    'tags': doc.tags,
                    'create_date': doc.create_date,
                    'sismics_id': doc.id
                },
                score=score * self.sismics_weight,
                doc_id=doc.id
            ))

        return results

    def _retrieve_vector(self, query: str, n_results: int) -> List[RetrievalResult]:
        """Retrieve from vector store (semantic search)"""
        search_results = self.vector_store.search(query, n_results=n_results)

        results = []
        for result in search_results:
            # ChromaDB distance: lower is better, convert to similarity score
            # Assuming L2 distance, normalize to 0-1 range
            similarity = 1.0 / (1.0 + result.score)

            results.append(RetrievalResult(
                content=result.content,
                source='vector',
                metadata=result.metadata,
                score=similarity * self.vector_weight,
                doc_id=result.document_id
            ))

        return results

    async def _retrieve_graph(self, query: str, num_results: int) -> List[RetrievalResult]:
        """Retrieve from knowledge graph (entity-based queries)"""
        graph_results = await self.graph_builder.query(query, num_results=num_results)

        if not graph_results:
            return []

        results = []
        for idx, result in enumerate(graph_results):
            # Graph results are facts, convert to score based on rank
            score = 1.0 / (idx + 1)

            results.append(RetrievalResult(
                content=result.fact if hasattr(result, 'fact') else str(result),
                source='graph',
                metadata={
                    'type': 'knowledge_graph_fact',
                    'rank': idx + 1
                },
                score=score * self.graph_weight,
                doc_id=None
            ))

        return results

    def _reciprocal_rank_fusion(self, results: List[RetrievalResult], top_k: int, k: int = 60) -> List[RetrievalResult]:
        """
        Reciprocal Rank Fusion (RRF) to combine rankings from multiple sources

        RRF formula: score = sum(1 / (k + rank)) for each source
        where k is a constant (typically 60)

        Args:
            results: All results from different sources
            top_k: Number of final results to return
            k: RRF constant (default 60)

        Returns:
            Fused and ranked results
        """
        # Group by content (deduplicate similar content)
        content_map: Dict[str, List[RetrievalResult]] = {}

        for result in results:
            # Use first 200 chars as key for deduplication
            key = result.content[:200] if result.content else str(result.metadata)

            if key not in content_map:
                content_map[key] = []
            content_map[key].append(result)

        # Calculate RRF scores
        fused_results = []
        for key, result_group in content_map.items():
            # Combine scores from all sources that returned this content
            rrf_score = 0.0
            best_result = result_group[0]  # Use first as representative

            for result in result_group:
                # Each source contributes to RRF score
                rank = int(1.0 / result.score) if result.score > 0 else 1000
                rrf_score += 1.0 / (k + rank)

            # Update score to RRF score
            best_result.score = rrf_score
            fused_results.append(best_result)

        # Sort by RRF score and take top_k
        ranked = sorted(fused_results, key=lambda x: x.score, reverse=True)[:top_k]

        return ranked

    async def get_context(
        self,
        query: str,
        top_k: int = 5,
        max_chars: int = 4000
    ) -> str:
        """
        Get retrieval context as formatted string for LLM

        Args:
            query: Query to retrieve context for
            top_k: Number of results to retrieve
            max_chars: Maximum characters in context

        Returns:
            Formatted context string
        """
        results = await self.retrieve(query, top_k=top_k)

        if not results:
            return "No relevant context found."

        context_parts = []
        total_chars = 0

        for idx, result in enumerate(results, 1):
            # Format: [Source N] Content (metadata)
            source_label = f"[{result.source.upper()} {idx}]"

            content_preview = result.content[:500] if result.content else "(No content)"

            metadata_str = ""
            if result.metadata:
                # Show relevant metadata
                if 'title' in result.metadata:
                    metadata_str = f"Title: {result.metadata['title']}"
                elif 'filename' in result.metadata:
                    metadata_str = f"File: {result.metadata['filename']}"

            part = f"{source_label} {content_preview}"
            if metadata_str:
                part += f"\n({metadata_str})"

            part_len = len(part)
            if total_chars + part_len > max_chars:
                break

            context_parts.append(part)
            total_chars += part_len

        return "\n\n".join(context_parts)

    async def close(self):
        """Close all connections"""
        if self.sismics:
            await self.sismics.close()
        await self.graph_builder.close()


# Convenience function
async def hybrid_retrieve(
    query: str,
    top_k: int = 5,
    return_context: bool = False
) -> List[RetrievalResult] | str:
    """
    Quick hybrid retrieval

    Args:
        query: Search query
        top_k: Number of results
        return_context: If True, return formatted context string instead of results

    Returns:
        List of results or formatted context string
    """
    rag = HybridRAG()
    try:
        await rag.initialize()

        if return_context:
            return await rag.get_context(query, top_k=top_k)
        else:
            return await rag.retrieve(query, top_k=top_k)

    finally:
        await rag.close()

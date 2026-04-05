"""
Semantic Enhancer with Domain Knowledge Graph
==============================================
Understands that "wind design engineer" relates to "energy engineering"
Uses knowledge graph + contextual embeddings for semantic matching beyond keywords.
"""

import json
from typing import List, Dict, Set, Optional
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer
from loguru import logger


class DomainKnowledgeGraph:
    """Knowledge graph for job domain relationships"""

    def __init__(self):
        """Initialize domain knowledge graph"""
        # Define domain relationships: parent → children concepts
        self.knowledge_graph = {
            # Energy Engineering domain
            "energy engineering": [
                "renewable energy", "wind energy", "solar energy", "grid engineering",
                "power systems", "energy storage", "smart grid", "energy efficiency"
            ],
            "wind energy": [
                "wind turbine design", "offshore wind", "wind farm", "blade design",
                "wind resource assessment", "wind power", "turbine control systems"
            ],
            "solar energy": [
                "photovoltaic systems", "solar panels", "solar thermal", "PV design",
                "solar forecasting", "solar farm"
            ],
            "grid engineering": [
                "power grid", "transmission", "distribution", "grid stability",
                "load balancing", "smart grid", "grid modernization", "microgrid"
            ],
            "power systems": [
                "electrical grid", "power flow", "voltage control", "power electronics",
                "energy management system", "SCADA", "grid optimization"
            ],

            # Machine Learning / AI domain
            "machine learning": [
                "deep learning", "neural networks", "computer vision", "NLP",
                "reinforcement learning", "supervised learning", "unsupervised learning",
                "time series forecasting", "predictive modeling"
            ],
            "deep learning": [
                "CNN", "RNN", "LSTM", "transformer", "GAN", "autoencoder",
                "neural architecture", "PyTorch", "TensorFlow"
            ],
            "data science": [
                "machine learning", "statistical analysis", "data mining",
                "data visualization", "predictive analytics", "big data"
            ],

            # Software Engineering domain
            "software engineering": [
                "backend development", "frontend development", "full stack",
                "DevOps", "cloud computing", "microservices", "API development"
            ],
            "cloud computing": [
                "AWS", "Azure", "GCP", "cloud architecture", "serverless",
                "containerization", "Kubernetes", "Docker"
            ],
            "DevOps": [
                "CI/CD", "infrastructure as code", "monitoring", "automation",
                "Kubernetes", "Docker", "Jenkins", "GitLab CI"
            ],

            # Research domain
            "research": [
                "PhD position", "postdoc", "research engineer", "research scientist",
                "scientific computing", "publications", "academic research"
            ],

            # Cross-domain: Energy + ML/AI
            "energy data science": [
                "energy forecasting", "load forecasting", "renewable forecasting",
                "smart grid analytics", "energy optimization", "digital twin"
            ],
            "energy machine learning": [
                "predictive maintenance", "energy forecasting", "grid optimization",
                "renewable energy prediction", "demand response", "anomaly detection"
            ]
        }

        # Reverse index: child → all parents
        self.reverse_graph = self._build_reverse_graph()

        # Synonym mapping
        self.synonyms = {
            "ML": "machine learning",
            "AI": "artificial intelligence",
            "DL": "deep learning",
            "CV": "computer vision",
            "NLP": "natural language processing",
            "PV": "photovoltaic",
            "EMS": "energy management system",
            "SCADA": "supervisory control and data acquisition",
            "CI/CD": "continuous integration continuous deployment",
            "K8s": "Kubernetes",
        }

    def _build_reverse_graph(self) -> Dict[str, List[str]]:
        """Build reverse lookup: concept → parent domains"""
        reverse = {}
        for parent, children in self.knowledge_graph.items():
            for child in children:
                if child not in reverse:
                    reverse[child] = []
                reverse[child].append(parent)
        return reverse

    def expand_concept(self, concept: str) -> Set[str]:
        """
        Expand a concept to related terms via knowledge graph.

        Example:
            "wind energy" → {"wind energy", "wind turbine design", "offshore wind", ...}
        """
        concept = concept.lower()

        # Check synonyms
        concept = self.synonyms.get(concept, concept)

        expanded = {concept}

        # Add children (more specific)
        if concept in self.knowledge_graph:
            expanded.update(self.knowledge_graph[concept])

        # Add parents (more general)
        if concept in self.reverse_graph:
            expanded.update(self.reverse_graph[concept])

        return expanded

    def semantic_similarity(self, concept1: str, concept2: str) -> float:
        """
        Calculate semantic similarity between two concepts.
        Returns 1.0 for exact match, 0.8 for related, 0.0 for unrelated.
        """
        c1_lower = concept1.lower()
        c2_lower = concept2.lower()

        # Exact match
        if c1_lower == c2_lower:
            return 1.0

        # Expand both concepts
        expanded1 = self.expand_concept(c1_lower)
        expanded2 = self.expand_concept(c2_lower)

        # Check overlap
        overlap = expanded1.intersection(expanded2)
        if overlap:
            return 0.85  # Strong semantic relationship

        # Check if one is parent/child of other
        if c1_lower in expanded2 or c2_lower in expanded1:
            return 0.75  # Related via hierarchy

        return 0.0  # Not related


class SemanticEnhancer:
    """
    Enhances job-CV matching with semantic understanding.
    Combines domain knowledge graph + contextual embeddings.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Args:
            model_name: Sentence transformer model for embeddings
                       Recommended: "BAAI/bge-base-en-v1.5" (better than MiniLM)
        """
        self.knowledge_graph = DomainKnowledgeGraph()
        self.model = SentenceTransformer(model_name)
        logger.info(f"Loaded semantic model: {model_name}")

    def enhance_job_description(self, job_description: str) -> Dict[str, any]:
        """
        Enhance job description with semantic expansions.

        Returns:
            {
                "original": str,
                "expanded_keywords": List[str],  # Semantically related terms
                "domain_tags": List[str],        # Identified domains
                "embedding": np.ndarray
            }
        """
        # Extract key phrases (simple keyword extraction)
        keywords = self._extract_keywords(job_description)

        # Expand using knowledge graph
        expanded = set()
        domains = set()
        for keyword in keywords:
            expansions = self.knowledge_graph.expand_concept(keyword)
            expanded.update(expansions)

            # Identify parent domains
            if keyword in self.knowledge_graph.reverse_graph:
                domains.update(self.knowledge_graph.reverse_graph[keyword])

        # Generate embedding
        embedding = self.model.encode(job_description, normalize_embeddings=True)

        return {
            "original": job_description,
            "extracted_keywords": list(keywords),
            "expanded_keywords": list(expanded),
            "domain_tags": list(domains),
            "embedding": embedding
        }

    def semantic_match_score(
        self,
        cv_skills: List[str],
        job_requirements: str,
        cv_embedding: Optional[np.ndarray] = None
    ) -> Dict[str, any]:
        """
        Calculate semantic match score between CV and job.

        Returns:
            {
                "score": float (0-10),
                "matched_skills": List[str],
                "semantic_matches": List[tuple],  # (cv_skill, job_req, similarity)
                "missing_domains": List[str]
            }
        """
        # Enhance job description
        job_enhanced = self.enhance_job_description(job_requirements)

        # Direct keyword matches
        direct_matches = []
        for skill in cv_skills:
            if skill.lower() in job_requirements.lower():
                direct_matches.append(skill)

        # Semantic matches via knowledge graph
        semantic_matches = []
        for skill in cv_skills:
            for job_keyword in job_enhanced["extracted_keywords"]:
                similarity = self.knowledge_graph.semantic_similarity(skill, job_keyword)
                if similarity >= 0.75:
                    semantic_matches.append((skill, job_keyword, similarity))

        # Embedding similarity (if CV embedding provided)
        embedding_score = 0.0
        if cv_embedding is not None:
            job_emb = job_enhanced["embedding"]
            embedding_score = float(np.dot(cv_embedding, job_emb))

        # Calculate final score
        keyword_score = len(direct_matches) * 0.5
        semantic_score = len(semantic_matches) * 0.3

        # Normalize to 0-10
        raw_score = min(keyword_score + semantic_score + embedding_score * 3, 10)

        # Identify missing domains
        cv_domains = set()
        for skill in cv_skills:
            if skill.lower() in self.knowledge_graph.reverse_graph:
                cv_domains.update(self.knowledge_graph.reverse_graph[skill.lower()])

        missing_domains = set(job_enhanced["domain_tags"]) - cv_domains

        return {
            "score": round(raw_score, 2),
            "matched_skills": direct_matches,
            "semantic_matches": semantic_matches,
            "missing_domains": list(missing_domains),
            "job_domains": job_enhanced["domain_tags"]
        }

    def _extract_keywords(self, text: str) -> Set[str]:
        """Simple keyword extraction (can be enhanced with NLP)"""
        # Common job-related technical terms
        technical_terms = [
            "python", "machine learning", "deep learning", "data science",
            "wind energy", "solar energy", "energy engineering", "power systems",
            "grid", "renewable", "AI", "ML", "cloud", "AWS", "Azure", "docker",
            "kubernetes", "devops", "backend", "frontend", "full stack",
            "research", "PhD", "engineering", "software"
        ]

        text_lower = text.lower()
        found = set()
        for term in technical_terms:
            if term.lower() in text_lower:
                found.add(term)

        return found


# Example usage
if __name__ == "__main__":
    enhancer = SemanticEnhancer()

    # Test: CV has "energy engineering", job asks for "wind design engineer"
    cv_skills = ["Energy Engineering", "Python", "Machine Learning", "Power Systems"]
    job_desc = """
    We are looking for a Wind Design Engineer with expertise in wind turbine design
    and renewable energy systems. Experience with grid integration is a plus.
    """

    result = enhancer.semantic_match_score(cv_skills, job_desc)
    print(f"Semantic Match Score: {result['score']}/10")
    print(f"Direct Matches: {result['matched_skills']}")
    print(f"Semantic Matches: {result['semantic_matches']}")
    print(f"Missing Domains: {result['missing_domains']}")

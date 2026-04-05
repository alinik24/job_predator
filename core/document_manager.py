"""
Document Manager - Handles user documents for job applications
Automatically detects, validates, and organizes application documents
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from core.config import settings, ROOT_DIR


@dataclass
class Document:
    """Represents a user document"""
    filename: str
    filepath: Path
    doc_type: str  # cv, cover_letter, certificate, transcript, residence_permit, other
    file_format: str  # pdf, docx, tex, jpg, png
    size_bytes: int
    uploaded_at: datetime
    metadata: Dict = None


class DocumentManager:
    """
    Manages user documents for job applications.
    Handles document detection, validation, organization, and retrieval.
    """

    DOCUMENT_TYPES = {
        "cv": ["cv", "resume", "lebenslauf"],
        "cover_letter": ["cover", "letter", "anschreiben", "motivationsschreiben"],
        "certificate": ["certificate", "zertifikat", "cert", "degree", "diploma"],
        "transcript": ["transcript", "tor", "zeugnis", "grades", "marks"],
        "residence_permit": ["aufenthalt", "permit", "visa", "residence", "work_permit"],
        "language_cert": ["toefl", "ielts", "goethe", "telc", "language"],
        "reference": ["reference", "recommendation", "referenz", "empfehlung"],
        "portfolio": ["portfolio", "work_sample", "project"],
        "other": []
    }

    SUPPORTED_FORMATS = [".pdf", ".docx", ".doc", ".tex", ".jpg", ".jpeg", ".png"]

    def __init__(self):
        self.documents_dir = Path(settings.documents_dir)
        self.documents: Dict[str, List[Document]] = {
            doc_type: [] for doc_type in self.DOCUMENT_TYPES.keys()
        }
        self._scan_documents()

    def _scan_documents(self):
        """Scan user_documents directory and categorize all files"""
        if not self.documents_dir.exists():
            logger.warning(f"Documents directory not found: {self.documents_dir}")
            return

        for root, dirs, files in os.walk(self.documents_dir):
            for filename in files:
                filepath = Path(root) / filename
                if filepath.suffix.lower() in self.SUPPORTED_FORMATS:
                    doc = self._create_document(filepath)
                    if doc:
                        self.documents[doc.doc_type].append(doc)

        logger.info(f"Document scan complete: {self.count_documents()} documents found")

    def _create_document(self, filepath: Path) -> Optional[Document]:
        """Create Document object from file"""
        try:
            doc_type = self._detect_document_type(filepath)
            return Document(
                filename=filepath.name,
                filepath=filepath,
                doc_type=doc_type,
                file_format=filepath.suffix.lower().lstrip('.'),
                size_bytes=filepath.stat().st_size,
                uploaded_at=datetime.fromtimestamp(filepath.stat().st_mtime),
                metadata={}
            )
        except Exception as e:
            logger.error(f"Failed to create document from {filepath}: {e}")
            return None

    def _detect_document_type(self, filepath: Path) -> str:
        """Auto-detect document type from path and filename"""
        path_str = str(filepath).lower()
        filename = filepath.name.lower()

        # Check parent directory name first
        parent_dir = filepath.parent.name.lower()
        for doc_type, keywords in self.DOCUMENT_TYPES.items():
            if doc_type in parent_dir:
                return doc_type

        # Then check filename
        for doc_type, keywords in self.DOCUMENT_TYPES.items():
            if any(keyword in filename for keyword in keywords):
                return doc_type

        # Default to other
        return "other"

    def get_cv(self) -> Optional[Document]:
        """Get primary CV document"""
        cvs = self.documents.get("cv", [])
        if not cvs:
            logger.warning("No CV found in user_documents/cv/")
            return None

        # Prefer PDF over other formats
        pdf_cvs = [cv for cv in cvs if cv.file_format == "pdf"]
        if pdf_cvs:
            return sorted(pdf_cvs, key=lambda x: x.uploaded_at, reverse=True)[0]

        return sorted(cvs, key=lambda x: x.uploaded_at, reverse=True)[0]

    def get_cover_letters(self) -> List[Document]:
        """Get all sample cover letters (for learning style)"""
        return self.documents.get("cover_letter", [])

    def get_certificates(self) -> List[Document]:
        """Get all certificates"""
        return self.documents.get("certificate", [])

    def get_transcripts(self) -> List[Document]:
        """Get all academic transcripts"""
        return self.documents.get("transcript", [])

    def get_residence_permits(self) -> List[Document]:
        """Get residence/work permits"""
        return self.documents.get("residence_permit", [])

    def get_document_by_type(self, doc_type: str) -> List[Document]:
        """Get all documents of a specific type"""
        return self.documents.get(doc_type, [])

    def count_documents(self) -> int:
        """Count total documents"""
        return sum(len(docs) for docs in self.documents.values())

    def get_missing_documents(self, required_types: List[str]) -> List[str]:
        """
        Check which required document types are missing.

        Args:
            required_types: List of document types needed (e.g., ["cv", "transcript"])

        Returns:
            List of missing document types
        """
        missing = []
        for doc_type in required_types:
            if not self.documents.get(doc_type):
                missing.append(doc_type)
        return missing

    def suggest_documents_for_job(self, job_description: str) -> Dict[str, List[Document]]:
        """
        Suggest which documents to attach based on job description.

        Args:
            job_description: Job description text

        Returns:
            Dict mapping reason -> list of suggested documents
        """
        suggestions = {
            "required": [],
            "recommended": [],
            "optional": []
        }

        # CV always required
        cv = self.get_cv()
        if cv:
            suggestions["required"].append(cv)

        job_lower = job_description.lower()

        # Check for keywords indicating specific document needs
        if any(word in job_lower for word in ["degree", "bachelor", "master", "phd", "academic"]):
            suggestions["recommended"].extend(self.get_certificates())
            suggestions["recommended"].extend(self.get_transcripts())

        if any(word in job_lower for word in ["international", "visa", "work permit", "eu citizen"]):
            suggestions["required"].extend(self.get_residence_permits())

        if any(word in job_lower for word in ["english", "german", "language", "fluent"]):
            language_certs = self.get_document_by_type("language_cert")
            if language_certs:
                suggestions["recommended"].extend(language_certs)

        if any(word in job_lower for word in ["portfolio", "samples", "previous work"]):
            portfolios = self.get_document_by_type("portfolio")
            if portfolios:
                suggestions["recommended"].extend(portfolios)

        return suggestions

    def get_summary(self) -> Dict:
        """Get summary of available documents"""
        return {
            "total_documents": self.count_documents(),
            "by_type": {
                doc_type: len(docs) for doc_type, docs in self.documents.items() if docs
            },
            "cv_available": self.get_cv() is not None,
            "cover_letter_samples": len(self.get_cover_letters()),
            "certificates": len(self.get_certificates()),
            "transcripts": len(self.get_transcripts()),
            "residence_permits": len(self.get_residence_permits()),
        }

    def ask_user_for_document(self, doc_type: str) -> str:
        """
        Generate a user-friendly message asking for a missing document.

        Args:
            doc_type: Type of document needed

        Returns:
            Formatted message to display to user
        """
        messages = {
            "cv": """
[CV] CV Required
Please add your CV to: user_documents/cv/
Supported formats: PDF, DOCX, LaTeX
Example: user_documents/cv/your_cv.pdf
            """,
            "transcript": """
[TRANSCRIPT] Academic Transcript Required
This job requires proof of education.
Please add your transcript to: user_documents/transcripts/
Example: user_documents/transcripts/BSc_TOR.pdf
            """,
            "certificate": """
[CERT] Certificate Required
This job requires degree certificates.
Please add to: user_documents/certificates/
Example: user_documents/certificates/BSc_Certificate.pdf
            """,
            "residence_permit": """
[PERMIT] Work Authorization Required
This job requires proof of work authorization.
Please add residence permit/visa to: user_documents/residence_permits/
Example: user_documents/residence_permits/aufenthaltstitel.pdf
            """,
            "language_cert": """
[LANG] Language Certificate Recommended
This job mentions language requirements.
If you have TOEFL/IELTS/Goethe, add to: user_documents/other/language_certificates/
            """,
        }

        return messages.get(doc_type, f"Document type '{doc_type}' is needed for this application.")


# Singleton instance
_document_manager: Optional[DocumentManager] = None


def get_document_manager() -> DocumentManager:
    """Get or create DocumentManager singleton"""
    global _document_manager
    if _document_manager is None:
        _document_manager = DocumentManager()
    return _document_manager

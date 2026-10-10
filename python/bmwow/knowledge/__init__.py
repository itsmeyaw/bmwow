"""Database-independent knowledge contracts and validated snapshot projections."""

from .combined import CombinedKnowledgeService
from .config import KnowledgeConfig, ModelProfile, SearchLocale, VfcMapping
from .factory import create_knowledge_service
from .feedback import (
    DataAvailability,
    FeedbackCoverage,
    FeedbackDataset,
    FeedbackKnowledgeService,
    FeedbackRepository,
    FeedbackServiceConfig,
    KnowledgeUnavailableError,
)
from .records import (
    AttributeValue,
    DocChunk,
    EvidenceReference,
    FeedbackAspect,
    FeedbackClassification,
    FeedbackFilter,
    FeedbackItem,
    FeedbackPage,
    FeedbackRetrieval,
    ModelNode,
    SalesRow,
    StudyScore,
)
from .repository import FileSnapshotRepository, InMemoryRepository, SnapshotRepository
from .service import KnowledgeService
from .synthetic import create_synthetic_service

__all__ = [
    "CombinedKnowledgeService",
    "FileSnapshotRepository",
    "create_knowledge_service",
    "AttributeValue",
    "DocChunk",
    "DataAvailability",
    "EvidenceReference",
    "FeedbackAspect",
    "FeedbackCoverage",
    "FeedbackDataset",
    "FeedbackClassification",
    "FeedbackFilter",
    "FeedbackItem",
    "FeedbackKnowledgeService",
    "FeedbackPage",
    "FeedbackRepository",
    "FeedbackRetrieval",
    "FeedbackServiceConfig",
    "InMemoryRepository",
    "KnowledgeConfig",
    "KnowledgeService",
    "KnowledgeUnavailableError",
    "ModelNode",
    "ModelProfile",
    "SalesRow",
    "SearchLocale",
    "SnapshotRepository",
    "StudyScore",
    "VfcMapping",
    "create_synthetic_service",
]

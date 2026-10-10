"""Database-independent knowledge contracts and validated snapshot projections."""

from .config import KnowledgeConfig, ModelProfile, SearchLocale, VfcMapping
from .records import (
    AttributeValue,
    DocChunk,
    EvidenceReference,
    FeedbackClassification,
    FeedbackFilter,
    FeedbackItem,
    ModelNode,
    SalesRow,
    StudyScore,
)
from .repository import InMemoryRepository, SnapshotRepository
from .service import KnowledgeService
from .synthetic import create_synthetic_service

__all__ = [
    "AttributeValue",
    "DocChunk",
    "EvidenceReference",
    "FeedbackClassification",
    "FeedbackFilter",
    "FeedbackItem",
    "InMemoryRepository",
    "KnowledgeConfig",
    "KnowledgeService",
    "ModelNode",
    "ModelProfile",
    "SalesRow",
    "SearchLocale",
    "SnapshotRepository",
    "StudyScore",
    "VfcMapping",
    "create_synthetic_service",
]

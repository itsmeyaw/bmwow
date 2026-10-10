"""Parameterized, read-only PostgreSQL adapter for the existing Neon feedback schema."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from pydantic import Field, SecretStr, ValidationError

from bmwow.ontology.models import Context, SqlLocator

from .config import Configuration
from .feedback import (
    FeedbackCoverage,
    FeedbackDataset,
    FeedbackKnowledgeService,
    FeedbackServiceConfig,
    aspect_id,
    feedback_id,
    vehicle_id,
)
from .records import (
    EvidenceReference,
    FeedbackAspect,
    FeedbackClassification,
    FeedbackFilter,
    FeedbackItem,
    FeedbackPage,
    FeedbackRetrieval,
)

DATA_LIMITATIONS = [
    "The SQL import does not identify a source version or original file/CSV location.",
    "Original unlabelled VFC classifications cannot be reconstructed from these tables.",
    "Feedback dates are unknown; created_at is an import timestamp.",
    "Feedback and aspect IDs resolve SQL read projections, not persisted ontology nodes.",
    "SQL citations resolve the current import; immutable dataset snapshots are not available.",
]
SELECTION_POLICY = "Feedback Explorer ID ascending; parent limit applied before aspects."


class NeonFeedbackConfig(Configuration):
    dataset_key: str = Field(default="bmw-feedback", pattern=r"^[a-zA-Z0-9_-]+$")
    default_limit: int = Field(default=200, ge=1)
    max_limit: int = Field(default=5000, ge=1)
    connect_timeout_seconds: int = Field(default=10, ge=1)
    statement_timeout_ms: int = Field(default=15000, ge=1)


class FeedbackStorageError(RuntimeError):
    """Sanitized operational failure: no DSN, feedback text, or SQL parameters in the message."""


def _where(filters: FeedbackFilter) -> tuple[str, list[Any]]:
    clauses, params = [], []
    for column, values in (
        ("derivate_code", [value.strip().upper() for value in filters.models]),
        ("country", [value.strip().upper() for value in filters.markets]),
        ("source", filters.sources),
    ):
        if values:
            clauses.append(f"{column} = ANY(%s)")
            params.append(values)
    if filters.engine_types:
        values = [value.strip().upper().replace("BEVE", "BEV") for value in filters.engine_types]
        known = [value for value in values if value != "UNKNOWN"]
        predicate = "engine_type = ANY(%s)"
        if "UNKNOWN" in values:
            predicate = f"({predicate} OR engine_type IS NULL)"
        clauses.append(predicate)
        params.append(known)
    if filters.since is not None:
        # No observation date exists. Never turn the import timestamp into a customer event date.
        clauses.append("FALSE")
    return " AND ".join(clauses) or "TRUE", params


def _locator(table: str, key: Any) -> SqlLocator:
    return SqlLocator(
        kind="sql", table=f"public.{table}", record_key=str(key), original_locator=None
    )


def _context(parent: Mapping) -> Context:
    derivate, country, engine = (
        parent.get("derivate_code"),
        parent.get("country"),
        parent.get("engine_type"),
    )
    engine = (engine or "unknown").lower().replace("beve", "bev")
    return Context(
        vehicle_model_ids=[vehicle_id(derivate)] if derivate else [],
        market_ids=[],
        country_codes=[country] if country else [],
        engine_types=[engine if engine in {"ice", "phev", "bev"} else "unknown"],
        as_of=None,
        scope_notes=[
            "Country and Derivate describe feedback coverage, not vehicle sale availability."
        ],
    )


def project_feedback(parent: Mapping, aspects: list[Mapping], dataset_key: str) -> FeedbackItem:
    """Preserve imported Verbatim and all aspects; no inference is promoted to a graph Signal."""
    item_id = feedback_id(dataset_key, parent["feedback_explorer_id"])
    source_id = f"source:{dataset_key}"
    context = _context(parent)
    reference = EvidenceReference(
        evidence_id=item_id,
        source_id=source_id,
        record_key=parent["feedback_explorer_id"],
        locator=_locator("feedback_entries", parent["id"]),
    )
    projected, classifications = [], []
    for value in aspects:
        locator = _locator("feedback_aspects", value["id"])
        quote = value.get("quote_snippet")
        curated = value["extraction_source"] == "vfc_label"
        status = (
            "not_applicable"
            if curated
            else "missing"
            if not quote or not quote.strip()
            else "supported"
            if quote in parent["raw_feedback"]
            else "mismatch"
        )
        limitations = []
        if status in {"missing", "mismatch"}:
            limitations.append(
                "This inferred aspect has no exact supporting Quote in the imported Verbatim."
            )
        if curated:
            limitations.append(
                "The original VFC label is curated; this does not establish human authorship "
                "of the coarse buckets or Sentiment Score."
            )
            classifications.append(
                FeedbackClassification(
                    feedback_type=value.get("feedback_type"),
                    # Legacy names carry original Aspect Term/Label, not the coarse SQL buckets.
                    vfc_category=value.get("aspect_term"),
                    vfc_issue=value.get("aspect_label_raw"),
                    vfc_combined=None,
                    attribute=None,
                    mapping_status=None,
                    locator=locator,
                )
            )
        projected.append(
            FeedbackAspect(
                aspect_id=aspect_id(dataset_key, str(value["id"])),
                locator=locator,
                feedback_type=value.get("feedback_type"),
                aspect_term=value.get("aspect_term"),
                aspect_label=value.get("aspect_label_raw"),
                vfc_category=value["vfc_category"],
                issue_type=value["issue_type"],
                sentiment=value["sentiment"],
                sentiment_score=value.get("sentiment_score"),
                extraction_source=value["extraction_source"],
                quote=quote,
                quote_status=status,
                imported_at=value.get("created_at"),
                references=[reference.model_copy(deep=True)],
                context=context,
                limitations=limitations,
            )
        )
    return FeedbackItem(
        item_id=item_id,
        text=parent["raw_feedback"],
        channel=parent.get("source"),
        market=parent.get("country"),
        model=parent.get("derivate_code"),
        engine_type=parent.get("engine_type"),
        imported_at=parent.get("created_at"),
        references=[reference],
        context=context,
        limitations=list(DATA_LIMITATIONS),
        classifications=classifications,
        aspects=projected,
    )


class NeonFeedbackRepository:
    """Each operation owns one short read-only transaction and closes its connection."""

    def __init__(
        self,
        database_url: str,
        config: NeonFeedbackConfig | None = None,
        *,
        connect: Callable = psycopg.connect,
    ) -> None:
        if not database_url.strip():
            raise ValueError("DATABASE_URL is required for Neon feedback reads.")
        self._database_url = SecretStr(database_url)
        self._config = (config or NeonFeedbackConfig()).model_copy(deep=True)
        if self._config.default_limit > self._config.max_limit:
            raise ValueError("default_limit must not exceed max_limit.")
        self._connect = connect

    @property
    def config(self) -> NeonFeedbackConfig:
        return self._config.model_copy(deep=True)

    @classmethod
    def from_env(cls, config: NeonFeedbackConfig | None = None) -> NeonFeedbackRepository:
        return cls(os.environ.get("DATABASE_URL", ""), config)

    @contextmanager
    def _read(self) -> Iterator[Any]:
        try:
            with self._connect(
                self._database_url.get_secret_value(),
                connect_timeout=self._config.connect_timeout_seconds,
                row_factory=dict_row,
                prepare_threshold=None,
            ) as conn:
                conn.read_only = True
                conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                conn.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                yield conn
        except psycopg.Error:
            raise FeedbackStorageError(
                "Feedback database read failed. Check connectivity, credentials, and the "
                "feedback schema; no fallback dataset was selected."
            ) from None
        except (ValidationError, KeyError, TypeError):
            raise FeedbackStorageError("Feedback data does not match the read contract.") from None

    def dataset(self) -> FeedbackDataset:
        return FeedbackDataset(
            source_id=f"source:{self._config.dataset_key}",
            dataset_key=self._config.dataset_key,
            limitations=list(DATA_LIMITATIONS),
        )

    def _project(self, conn, parents: list[dict]) -> list[FeedbackItem]:
        if not parents:
            return []
        aspects = conn.execute(
            "SELECT id, feedback_entry_id, feedback_type, vfc_category, aspect_term, "
            "aspect_label_raw, issue_type, quote_snippet, sentiment, sentiment_score, "
            "extraction_source, created_at FROM public.feedback_aspects "
            "WHERE feedback_entry_id = ANY(%s::uuid[]) ORDER BY feedback_entry_id, id",
            ([str(parent["id"]) for parent in parents],),
        ).fetchall()
        grouped: dict[str, list] = {}
        for aspect in aspects:
            grouped.setdefault(str(aspect["feedback_entry_id"]), []).append(aspect)
        return [
            project_feedback(parent, grouped.get(str(parent["id"]), []), self._config.dataset_key)
            for parent in parents
        ]

    def read_feedback(self, filters: FeedbackFilter) -> FeedbackPage:
        predicate, params = _where(filters)
        requested = self._config.default_limit if filters.limit is None else filters.limit
        limit = min(requested, self._config.max_limit)
        with self._read() as conn:
            total = conn.execute(
                f"SELECT count(*) AS n FROM public.feedback_entries WHERE {predicate}", params
            ).fetchone()["n"]
            parents = conn.execute(
                "SELECT id, feedback_explorer_id, source, brand, sales_description, country, "
                "derivate_code, engine_type, raw_feedback, created_at "
                f"FROM public.feedback_entries WHERE {predicate} "
                'ORDER BY feedback_explorer_id COLLATE "C", id LIMIT %s',
                [*params, limit],
            ).fetchall()
            items = self._project(conn, parents)
        limitations = ["The retrieved corpus is not a representative customer-population sample."]
        if total > len(items):
            limitations.append(
                "A bounded selection was returned; shares apply to selected feedback."
            )
        if requested > limit:
            limitations.append(
                f"The requested limit was capped at {self._config.max_limit} feedbacks."
            )
        if filters.since is not None:
            limitations.append(
                "The since filter excludes undated feedback; import dates are not used."
            )
        retrieval = FeedbackRetrieval(
            total_matching=total,
            returned_count=len(items),
            truncated=total > len(items),
            selection_policy=SELECTION_POLICY,
            limitations=limitations,
        )
        for item in items:
            item.retrieval = retrieval.model_copy(deep=True)
            item.limitations.extend(limitations)
        return FeedbackPage(items=items, retrieval=retrieval)

    def coverage(self) -> list[FeedbackCoverage]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT derivate_code, array_agg(DISTINCT country ORDER BY country) AS countries, "
                "array_agg(DISTINCT engine_type ORDER BY engine_type) AS engine_types, count(*) AS n, "
                "CASE WHEN count(DISTINCT brand) = 1 THEN min(brand) END AS brand, "
                "CASE WHEN count(DISTINCT sales_description) = 1 THEN min(sales_description) "
                "END AS sales_description FROM public.feedback_entries "
                "WHERE derivate_code IS NOT NULL GROUP BY derivate_code ORDER BY derivate_code"
            ).fetchall()
            return [
                FeedbackCoverage(
                    derivate=row["derivate_code"],
                    countries=[c for c in row["countries"] if c],
                    engine_types=[e for e in row["engine_types"] if e],
                    feedback_count=row["n"],
                    brand=row["brand"],
                    sales_description=row["sales_description"],
                )
                for row in rows
            ]

    def find_feedback(self, feedback_explorer_id: str) -> FeedbackItem | None:
        with self._read() as conn:
            parents = conn.execute(
                "SELECT id, feedback_explorer_id, source, brand, sales_description, country, "
                "derivate_code, engine_type, raw_feedback, created_at "
                "FROM public.feedback_entries WHERE feedback_explorer_id = %s",
                (feedback_explorer_id,),
            ).fetchall()
            items = self._project(conn, parents)
            return items[0] if items else None

    def find_aspect(self, aspect_id: str) -> FeedbackAspect | None:
        try:
            UUID(aspect_id)
        except ValueError:
            return None
        with self._read() as conn:
            parents = conn.execute(
                "SELECT f.id, f.feedback_explorer_id, f.source, f.brand, f.sales_description, "
                "f.country, f.derivate_code, f.engine_type, f.raw_feedback, f.created_at "
                "FROM public.feedback_entries f JOIN public.feedback_aspects a "
                "ON a.feedback_entry_id = f.id WHERE a.id = %s::uuid",
                (aspect_id,),
            ).fetchall()
            items = self._project(conn, parents)
            target = f"aspect:{self._config.dataset_key}:{aspect_id}"
            return next((a for item in items for a in item.aspects if a.aspect_id == target), None)


def create_neon_feedback_service(
    database_url: str | None = None,
    *,
    repository_config: NeonFeedbackConfig | None = None,
    service_config: FeedbackServiceConfig | None = None,
) -> FeedbackKnowledgeService:
    repository = (
        NeonFeedbackRepository.from_env(repository_config)
        if database_url is None
        else NeonFeedbackRepository(database_url, repository_config)
    )
    return FeedbackKnowledgeService(repository, service_config)

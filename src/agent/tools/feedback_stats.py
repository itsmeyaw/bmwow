"""Deterministic feedback statistics: dedupe → embed → cluster (AGENT_SPEC §6.3).

Counts and shares come from here, never from an LLM. Shares are relative to the deduplicated corpus,
so cluster shares plus the noise share sum to 1.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from langchain_core.embeddings import Embeddings
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.metrics import silhouette_score

from .knowledge import FeedbackItem

NEAR_DUP_COSINE = 0.95
MAX_REPRESENTATIVES = 8
KMEANS_K_RANGE = (4, 20)
EMBED_BATCH = 256

Method = Literal["auto", "hdbscan", "kmeans"]


@dataclass
class Cluster:
    label: int
    members: list[int]  # indices into FeedbackClustering.items
    representatives: list[int]  # closest to the centroid, best first

    @property
    def size(self) -> int:
        return len(self.members)


@dataclass
class FeedbackClustering:
    items: list[FeedbackItem]  # after dedupe
    n_items: int  # before dedupe
    clusters: list[Cluster]
    noise: list[int] = field(default_factory=list)
    method: str = ""

    @property
    def n_after_dedupe(self) -> int:
        return len(self.items)

    @property
    def noise_share(self) -> float:
        return len(self.noise) / self.n_after_dedupe if self.items else 0.0

    def share(self, cluster: Cluster) -> float:
        return cluster.size / self.n_after_dedupe if self.items else 0.0


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def exact_dedupe(items: list[FeedbackItem]) -> list[FeedbackItem]:
    seen: set[str] = set()
    out: list[FeedbackItem] = []
    for item in items:
        key = normalize_text(item.text)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _unit(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.where(norms == 0, 1, norms)


def near_dedupe(vectors: np.ndarray, threshold: float = NEAR_DUP_COSINE) -> list[int]:
    """Indices to keep: the first of every group of items with cosine similarity > threshold."""
    keep: list[int] = []
    kept_vecs: list[np.ndarray] = []
    for i, v in enumerate(vectors):
        if kept_vecs and float(np.max(np.stack(kept_vecs) @ v)) > threshold:
            continue
        keep.append(i)
        kept_vecs.append(v)
    return keep


def _kmeans(x: np.ndarray) -> np.ndarray:
    n = len(x)
    lo, hi = KMEANS_K_RANGE
    hi = min(hi, n - 1)
    if hi < 2:
        return np.zeros(n, dtype=int)
    best_labels, best_score = None, -2.0
    for k in range(min(lo, hi), hi + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(x)
        score = silhouette_score(x, labels, metric="cosine")
        if score > best_score:
            best_labels, best_score = labels, score
    return best_labels  # type: ignore[return-value]


def _hdbscan(x: np.ndarray) -> np.ndarray:
    return HDBSCAN(min_cluster_size=max(5, len(x) // 40), min_samples=3, metric="euclidean", copy=True).fit_predict(x)


def cluster_vectors(x: np.ndarray, method: Method = "auto") -> tuple[np.ndarray, str]:
    """Return labels (-1 = noise) and the method used. `auto` falls back from HDBSCAN to KMeans when
    HDBSCAN finds fewer than two clusters or labels most items as noise."""
    if len(x) < 8:
        return np.zeros(len(x), dtype=int), "single"
    if method in ("auto", "hdbscan"):
        labels = _hdbscan(x)
        n_clusters = len(set(labels) - {-1})
        if method == "hdbscan" or (n_clusters >= 2 and float(np.mean(labels == -1)) <= 0.5):
            return labels, "hdbscan"
    return _kmeans(x), "kmeans"


async def embed_texts(embeddings: Embeddings, texts: list[str]) -> np.ndarray:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        vectors += await embeddings.aembed_documents(texts[start:start + EMBED_BATCH])
    return _unit(np.asarray(vectors, dtype=float))


async def analyze_feedback(items: list[FeedbackItem], embeddings: Embeddings,
                           method: Method = "auto") -> FeedbackClustering:
    n_items = len(items)
    unique = exact_dedupe(items)
    if not unique:
        return FeedbackClustering(items=[], n_items=n_items, clusters=[])
    vectors = await embed_texts(embeddings, [i.text for i in unique])
    keep = near_dedupe(vectors)
    unique = [unique[i] for i in keep]
    vectors = vectors[keep]

    labels, used = cluster_vectors(vectors, method)
    clusters: list[Cluster] = []
    for label in sorted(set(labels) - {-1}):
        members = [int(i) for i in np.flatnonzero(labels == label)]
        centroid = _unit(vectors[members].mean(axis=0, keepdims=True))[0]
        order = np.argsort(-(vectors[members] @ centroid), kind="stable")
        reps = [members[int(j)] for j in order[:MAX_REPRESENTATIVES]]
        clusters.append(Cluster(label=int(label), members=members, representatives=reps))
    clusters.sort(key=lambda c: -c.size)
    noise = [int(i) for i in np.flatnonzero(labels == -1)]
    return FeedbackClustering(items=unique, n_items=n_items, clusters=clusters, noise=noise, method=used)

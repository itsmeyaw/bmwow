"""Statistics computed by code, never by an LLM: intervals, a region test and value distributions.

Plain `math` only, so the module ports directly to TypeScript.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Z95 = 1.959963984540054


def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for the proportion k / n (stable for small n and k near 0 or n)."""
    if n <= 0:
        return 0.0, 0.0
    if not 0 <= k <= n:
        raise ValueError(f"k={k} must lie between 0 and n={n}")
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    low = 0.0 if k == 0 else max(0.0, centre - half)
    high = 1.0 if k == n else min(1.0, centre + half)
    return low, high


def normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def two_proportion_p(k1: int, n1: int, k2: int, n2: int) -> float | None:
    """Two-sided p-value of a pooled two-proportion z-test; None when it is undefined."""
    if n1 <= 0 or n2 <= 0:
        return None
    pooled = (k1 + k2) / (n1 + n2)
    var = pooled * (1 - pooled) * (1 / n1 + 1 / n2)
    if var <= 0:
        return None
    return normal_two_sided_p((k1 / n1 - k2 / n2) / math.sqrt(var))


def is_thin(k: int, n: int, min_n: int, min_k: int) -> bool:
    return n < min_n or k < min_k


@dataclass(frozen=True)
class Distribution:
    n: int
    minimum: float
    median: float
    maximum: float


def distribution(values: list[float]) -> Distribution | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return Distribution(len(ordered), ordered[0], median, ordered[-1])


def rank_position(value: float, others: list[float], higher_is_better: bool) -> tuple[int, int]:
    """1-based rank of `value` among `others` + itself (1 = best) and the field size."""
    better = sum(1 for o in others if (o > value if higher_is_better else o < value))
    return better + 1, len(others) + 1


def relative_difference(value: float, reference: float) -> float | None:
    """(value - reference) / |reference|; None when the reference is 0."""
    if reference == 0:
        return None
    return (value - reference) / abs(reference)

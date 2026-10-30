"""Small statistics helpers: pass@k, pass^k, confidence intervals, Fisher's exact test."""

from __future__ import annotations

import math
from collections.abc import Sequence


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that at least one of k samples (from n trials, c passing) passes.

    Unbiased estimator from Chen et al. (2021), "Evaluating Large Language Models Trained on Code".
    """
    if k > n:
        k = n
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Probability that all k samples pass (pass^k from tau-bench): a reliability measure."""
    if k > n:
        k = n
    if k == 0:
        return 1.0
    return math.comb(c, k) / math.comb(n, k)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher's exact test p-value for the 2x2 table [[a, b], [c, d]].

    Used to say whether a pass-rate change between two runs is distinguishable from noise.
    """
    n = a + b + c + d
    row1, col1 = a + b, a + c

    def prob(x: int) -> float:
        return math.comb(col1, x) * math.comb(n - col1, row1 - x) / math.comb(n, row1)

    lo, hi = max(0, row1 + col1 - n), min(row1, col1)
    p_obs = prob(a)
    total = sum(p for x in range(lo, hi + 1) if (p := prob(x)) <= p_obs * (1 + 1e-9))
    return min(1.0, total)


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]."""
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)

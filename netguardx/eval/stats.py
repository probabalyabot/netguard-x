"""Small statistics helpers for the evaluation harness (no dependencies beyond the standard library)."""
from __future__ import annotations

import math
import statistics
from typing import Optional

# two-sided 95% critical values of Student's t, by degrees of freedom
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
        10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
        19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042}


def t95(df: int) -> float:
    if df <= 0:
        raise ValueError("need at least two values for a confidence interval")
    if df in _T95:
        return _T95[df]
    if df < 30:  # between tabulated values: use the next smaller df, which is slightly wider
        return _T95[max(k for k in _T95 if k < df)]
    return 1.96


def mean_ci(values: list[float]) -> tuple[float, Optional[float]]:
    """Mean and the half-width of its 95% confidence interval (None for fewer than two values)."""
    if not values:
        raise ValueError("no values")
    m = statistics.fmean(values)
    if len(values) < 2:
        return m, None
    return m, t95(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))

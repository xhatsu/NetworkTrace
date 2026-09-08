from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass


BOUNDS_US = tuple(round(1_000 * (120_000 ** (i / 47))) for i in range(48))


@dataclass
class Histogram:
    counts: list[int]

    @classmethod
    def empty(cls) -> "Histogram":
        return cls([0] * len(BOUNDS_US))

    @classmethod
    def loads(cls, value: str | None) -> "Histogram":
        if not value:
            return cls.empty()
        counts = json.loads(value)
        return cls((counts + [0] * len(BOUNDS_US))[: len(BOUNDS_US)])

    def add(self, duration_us: int, count: int = 1) -> None:
        self.counts[min(bisect.bisect_left(BOUNDS_US, max(0, duration_us)), len(BOUNDS_US) - 1)] += count

    def merge(self, other: "Histogram") -> None:
        self.counts = [a + b for a, b in zip(self.counts, other.counts)]

    def percentile(self, q: float) -> float:
        total = sum(self.counts)
        if total == 0:
            return 0.0
        target = max(1, math.ceil(total * q))
        seen = 0
        for index, count in enumerate(self.counts):
            seen += count
            if seen >= target:
                return BOUNDS_US[index] / 1000.0
        return BOUNDS_US[-1] / 1000.0

    def dumps(self) -> str:
        return json.dumps(self.counts, separators=(",", ":"))


def merged_percentiles(values: list[str]) -> dict[str, float]:
    hist = Histogram.empty()
    for value in values:
        hist.merge(Histogram.loads(value))
    return {"p50_ms": hist.percentile(0.5), "p95_ms": hist.percentile(0.95), "p99_ms": hist.percentile(0.99)}


from __future__ import annotations

import time
import typing as t
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class Counter:
    name: str
    help: str
    values: Dict[Tuple, float] = field(default_factory=dict)

    def inc(self, value: float = 1.0, **labels: Any) -> None:
        key = tuple(sorted(labels.items()))
        self.values[key] = self.values.get(key, 0.0) + value


@dataclass
class Histogram:
    name: str
    help: str
    buckets: List[float]
    counts: Dict[Tuple, List[int]] = field(default_factory=dict)

    def observe(self, val: float, **labels: Any) -> None:
        key = tuple(sorted(labels.items()))
        if key not in self.counts:
            self.counts[key] = [0 for _ in self.buckets]
        for i, b in enumerate(self.buckets):
            if val <= b:
                self.counts[key][i] += 1
                break


# Predefined metrics
mcp_session_total = Counter("mcp_session_total", "Total sessions by status")
mcp_storage_latency_seconds = Histogram(
    "mcp_storage_latency_seconds",
    "Storage operation latency",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)
mcp_cache_hit_ratio = Counter("mcp_cache_hit_ratio", "Cache hits vs misses")
mcp_event_store_size_bytes = Counter("mcp_event_store_size_bytes", "Event store growth (approx)")
mcp_wrapper_overhead_seconds = Histogram(
    "mcp_wrapper_overhead_seconds",
    "Wrapper processing overhead",
    buckets=[0.0005, 0.001, 0.002, 0.005, 0.01, 0.02],
)



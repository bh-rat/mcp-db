from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, Optional, List


@dataclass
class CacheConfig:
    l1_enabled: bool = True
    l1_max_size: int = 1000
    l1_ttl_seconds: int = 60


@dataclass
class SessionConfig:
    ttl_seconds: int = 3600
    max_events_per_session: int = 10000
    snapshot_interval: int = 100


@dataclass
class ResilienceConfig:
    circuit_breaker_enabled: bool = True
    fallback_to_memory: bool = True
    retry_max_attempts: int = 3
    retry_backoff_ms: List[int] = dataclasses.field(default_factory=lambda: [100, 500, 2000])


@dataclass
class PerformanceConfig:
    batch_size: int = 100
    flush_interval_ms: int = 100
    compression_enabled: bool = False
    async_operations: bool = True


@dataclass
class StorageConfig:
    type: str = "memory"  # memory | redis | postgres | mongodb | dynamodb
    connection_string: Optional[str] = None
    connection_pool_size: int = 20
    timeout_seconds: int = 5


@dataclass
class WrapperConfig:
    storage: StorageConfig = dataclasses.field(default_factory=StorageConfig)
    session: SessionConfig = dataclasses.field(default_factory=SessionConfig)
    cache: CacheConfig = dataclasses.field(default_factory=CacheConfig)
    resilience: ResilienceConfig = dataclasses.field(default_factory=ResilienceConfig)
    performance: PerformanceConfig = dataclasses.field(default_factory=PerformanceConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WrapperConfig":
        def build(dc_cls, key):
            values = data.get(key, {})
            return dc_cls(**values)

        return cls(
            storage=build(StorageConfig, "storage"),
            session=build(SessionConfig, "session"),
            cache=build(CacheConfig, "cache"),
            resilience=build(ResilienceConfig, "resilience"),
            performance=build(PerformanceConfig, "performance"),
        )



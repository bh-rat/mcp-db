"""Unit tests for LocalCache."""

import time

from mcp_db.cache.local_cache import LocalCache


class TestLocalCache:
    """Test LocalCache implementation."""

    def test_cache_get_miss(self):
        """Test cache miss returns None."""
        cache = LocalCache(max_size=10, ttl_seconds=60)
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_set_and_get(self):
        """Test basic cache set and get operations."""
        cache = LocalCache(max_size=10, ttl_seconds=60)

        # Set a value
        cache.set("key1", "value1")

        # Get should return the value
        assert cache.get("key1") == "value1"

        # Set different types
        cache.set("key2", 42)
        cache.set("key3", {"nested": "dict"})
        cache.set("key4", ["list", "items"])

        assert cache.get("key2") == 42
        assert cache.get("key3") == {"nested": "dict"}
        assert cache.get("key4") == ["list", "items"]

    def test_cache_delete(self):
        """Test cache deletion."""
        cache = LocalCache()

        # Set and verify
        cache.set("to_delete", "value")
        assert cache.get("to_delete") == "value"

        # Delete and verify gone
        cache.delete("to_delete")
        assert cache.get("to_delete") is None

        # Delete non-existent key should not error
        cache.delete("nonexistent")

    def test_cache_clear(self):
        """Test clearing entire cache."""
        cache = LocalCache()

        # Add multiple items
        for i in range(5):
            cache.set(f"key{i}", f"value{i}")

        # Verify they exist
        assert cache.get("key0") == "value0"
        assert cache.get("key4") == "value4"

        # Clear cache
        cache.clear()

        # Verify all gone
        for i in range(5):
            assert cache.get(f"key{i}") is None

    def test_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        cache = LocalCache(max_size=3, ttl_seconds=60)

        # Fill cache
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Access key1 and key3 to make them recently used
        cache.get("key1")
        cache.get("key3")

        # Add new item - should evict key2 (least recently used)
        cache.set("key4", "value4")

        assert cache.get("key1") == "value1"  # Still there
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"  # Still there
        assert cache.get("key4") == "value4"  # New item

    def test_ttl_expiration(self):
        """Test TTL expiration of cached items."""
        cache = LocalCache(max_size=10, ttl_seconds=0.1)  # 100ms TTL

        cache.set("expires", "value")

        # Should exist immediately
        assert cache.get("expires") == "value"

        # Wait for expiration
        time.sleep(0.15)

        # Should be expired
        assert cache.get("expires") is None

    def test_custom_ttl_per_item(self):
        """Test setting custom TTL per item."""
        cache = LocalCache(max_size=10, ttl_seconds=10)  # Default 10s

        # Set with custom TTL
        cache.set("custom", "value", ttl_seconds=0.1)  # 100ms
        cache.set("default", "value2")  # Uses default 10s

        # Both should exist
        assert cache.get("custom") == "value"
        assert cache.get("default") == "value2"

        # Wait for custom to expire
        time.sleep(0.15)

        # Custom expired, default still there
        assert cache.get("custom") is None
        assert cache.get("default") == "value2"

    def test_cache_capacity_edge_cases(self):
        """Test edge cases for cache capacity."""
        # Single item cache
        cache = LocalCache(max_size=1, ttl_seconds=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"

        # Zero or negative size should still allow operation
        cache = LocalCache(max_size=0, ttl_seconds=60)
        cache.set("key", "value")  # Should not crash

        # Large cache
        large_cache = LocalCache(max_size=10000, ttl_seconds=60)
        for i in range(1000):
            large_cache.set(f"key{i}", f"value{i}")

        # Verify some samples
        assert large_cache.get("key0") == "value0"
        assert large_cache.get("key999") == "value999"

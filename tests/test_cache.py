import time

from x402_identity_guard.cache import TTLCache


def test_set_and_get():
    cache = TTLCache(ttl_seconds=60)
    cache.set("k", "v")
    assert cache.get("k") == "v"


def test_missing_key_returns_none():
    cache = TTLCache(ttl_seconds=60)
    assert cache.get("nope") is None


def test_entry_expires_after_ttl():
    cache = TTLCache(ttl_seconds=0.05)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    time.sleep(0.1)
    assert cache.get("k") is None


def test_invalidate_removes_entry():
    cache = TTLCache(ttl_seconds=60)
    cache.set("k", "v")
    cache.invalidate("k")
    assert cache.get("k") is None


def test_invalidate_missing_key_is_a_noop():
    cache = TTLCache(ttl_seconds=60)
    cache.invalidate("nope")  # should not raise

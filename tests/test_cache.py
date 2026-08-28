from schwabber.cache import TtlLruCache


def test_cache_expires_and_evicts_oldest_entry() -> None:
    now = [0.0]
    cache = TtlLruCache[str, int](max_entries=2, clock=lambda: now[0])
    cache.set("a", 1, 5)
    cache.set("b", 2, 5)
    cache.set("c", 3, 5)
    assert cache.get("a") is None
    now[0] = 6
    assert cache.get("b") is None

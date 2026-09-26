"""keypool tests: parsing, rotation, cooldown/backoff, thread safety."""
from __future__ import annotations

import threading
import time

import src.keypool as K
from src.keypool import KeyPool


def test_split_and_count():
    assert K.split_keys("a,b,,c ") == ["a", "b", "c"]
    assert K.split_keys("single") == ["single"]
    assert K.split_keys(["a", " b "]) == ["a", "b"]
    assert K.split_keys("") == [] and K.split_keys(None) == []
    assert K.count_keys("a,b") == 2


def test_round_robin_order():
    p = KeyPool("k1,k2,k3")
    assert [p.next() for _ in range(4)] == ["k1", "k2", "k3", "k1"]


def test_quota_key_skipped_until_cooldown(monkeypatch):
    p = KeyPool(["a", "b"])
    now = [1000.0]
    monkeypatch.setattr(K.time, "monotonic", lambda: now[0])
    p.report_quota("a")
    assert p.next() == "b"
    assert p.next() == "b"  # a still cooling (60s)
    now[0] += 61
    assert p.next() in ("a", "b")  # a recovered into rotation


def test_backoff_doubles_and_caps(monkeypatch):
    p = KeyPool(["a"])
    now = [0.0]
    monkeypatch.setattr(K.time, "monotonic", lambda: now[0])
    p.report_quota("a")
    assert p._cooldown_until["a"] == 60.0
    p.report_quota("a")
    assert p._cooldown_until["a"] == 120.0
    for _ in range(10):
        p.report_quota("a")
    assert p._cooldown_until["a"] - now[0] == K.MAX_COOLDOWN


def test_success_resets_backoff():
    p = KeyPool(["a", "b"])
    p.report_quota("a")
    p.report_success("a")
    assert p._cooldown_until == {} and p._backoff == {}


def test_all_cooling_returns_soonest(monkeypatch):
    p = KeyPool(["a", "b"])
    now = [500.0]
    monkeypatch.setattr(K.time, "monotonic", lambda: now[0])
    p.report_quota("a")  # cools until 560
    now[0] += 10
    p.report_quota("b")  # cools until 570
    assert p.next() == "a"


def test_empty_pool_raises():
    import pytest
    with pytest.raises(ValueError):
        KeyPool("").next()
    assert not KeyPool(None)


def test_thread_safety():
    p = KeyPool("a,b,c,d")
    seen = []
    lock = threading.Lock()

    def grab():
        for _ in range(250):
            k = p.next()
            with lock:
                seen.append(k)

    threads = [threading.Thread(target=grab) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == 1000
    assert set(seen) == {"a", "b", "c", "d"}


def test_is_quota_error():
    assert K.is_quota_error(None) is False
    err = Exception("429 Too Many Requests")
    err.code = 429
    assert K.is_quota_error(err) is True
    assert K.is_quota_error(Exception("quota exceeded")) is True
    assert K.is_quota_error(Exception("Rate Limit hit")) is True
    assert K.is_quota_error(Exception('{"message":"Too many requests"}')) is True
    assert K.is_quota_error(Exception("401 Unauthorized")) is False
    assert K.is_quota_error(Exception("timed out")) is False


def test_get_pool_caches_by_keyset():
    K._POOLS.clear()
    p1 = K.get_pool("x", "a,b")
    p2 = K.get_pool("x", "a,b")
    assert p1 is p2
    p3 = K.get_pool("x", "a,b,c")
    assert p3 is not p1 and len(p3) == 3
    K._POOLS.clear()


def test_get_pool_yields_clean_keys():
    # Regression: get_pool must not mangle keys via tuple/str round-trip.
    K._POOLS.clear()
    p = K.get_pool("y", ["k1", "k2"])
    assert p.keys == ["k1", "k2"]
    assert p.next() == "k1"
    K._POOLS.clear()

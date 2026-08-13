import threading
from concurrent.futures import ThreadPoolExecutor

from app.provider_cache import SingleFlightTTLCache


def test_single_flight_coalesces_equivalent_concurrent_loads():
    cache = SingleFlightTTLCache()
    loader_started = threading.Event()
    release_loader = threading.Event()
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        loader_started.set()
        assert release_loader.wait(timeout=2)
        return ("shared",)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(cache.get_or_load, "same", 60, loader) for _ in range(4)]
        assert loader_started.wait(timeout=2)
        release_loader.set()
        assert [future.result(timeout=2) for future in futures] == [("shared",)] * 4
    assert calls == 1


def test_failed_load_is_not_cached():
    cache = SingleFlightTTLCache()
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return "recovered"

    try:
        cache.get_or_load("key", 60, loader)
    except RuntimeError:
        pass
    assert cache.get_or_load("key", 60, loader) == "recovered"
    assert calls == 2

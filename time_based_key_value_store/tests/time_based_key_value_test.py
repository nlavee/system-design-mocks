import os
import sys
import pytest
import time
from threading import Thread

# Ensure project root is on sys.path so `src` package can be imported when tests run
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from src.time_based_key_value import TimeBasedKeyValue


@pytest.fixture
def kv_store():
    """Pytest fixture to create and properly stop the kv_store for each test."""
    store = TimeBasedKeyValue()
    yield store
    store.stop()


class TestTimeBasedKeyValue:

    def test_get_and_put(self, kv_store):
        """Tests basic get and put functionality, including out-of-order puts."""
        kv_store.put("a", "1", 1)
        kv_store.put("a", "24", 24)
        kv_store.put("a", "15", 15)
        
        # Give the worker thread time to process the puts
        time.sleep(0.1)

        assert kv_store.get("b", 400) == "", "Should return empty for non-existent key"
        assert kv_store.get("a", 0) == "", "Should return empty for timestamp before first entry"
        assert kv_store.get("a", 1) == "1", "Should get value at exact timestamp"
        assert kv_store.get("a", 10) == "1", "Should get latest value at or before timestamp"
        assert kv_store.get("a", 15) == "15", "Should handle out-of-order put correctly"
        assert kv_store.get("a", 30) == "24", "Should get latest value"

    def test_eviction_policy(self, kv_store):
        """Tests that the store only keeps the last 100 values for a key."""
        key = "eviction_test"
        # Put 105 items
        for i in range(105):
            kv_store.put(key, str(i), i)
        
        time.sleep(0.1)

        # The internal lists should be truncated to 100
        assert len(kv_store.keyValueDict[key][0]) == 100
        assert len(kv_store.keyValueDict[key][1]) == 100

        # The first value should now be for timestamp 5, not 0
        assert kv_store.get(key, 4) == ""
        assert kv_store.get(key, 5) == "5"

    def test_thread_safety(self, kv_store):
        """Tests that puts to the same and different keys are thread-safe."""
        num_threads = 10
        puts_per_thread = 50
        threads = []

        def worker_task(key):
            for i in range(puts_per_thread):
                kv_store.put(key, f"v{i}", i)

        # 5 threads writing to 'key_A'
        for _ in range(5):
            threads.append(Thread(target=worker_task, args=("key_A",)))
        
        # 5 threads writing to 'key_B'
        for _ in range(5):
            threads.append(Thread(target=worker_task, args=("key_B",)))

        for t in threads:
            t.start()
        
        for t in threads:
            t.join()

        time.sleep(0.1) # Allow queue to be processed

        # Check if data for key_A is consistent. 
        # It should have 50 unique timestamps (0-49), but since we have eviction,
        # it will be capped at 100 total entries.
        # The main check is that the lists are not corrupted and have the expected length.
        assert len(kv_store.keyValueDict["key_A"][0]) == 100
        assert len(kv_store.keyValueDict["key_A"][1]) == 100

        # Check data for key_B
        assert len(kv_store.keyValueDict["key_B"][0]) == 100
        assert len(kv_store.keyValueDict["key_B"][1]) == 100

        # Check that a final get works
        assert kv_store.get("key_A", 49) == "v49"
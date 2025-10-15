import time
from time_based_key_value import TimeBasedKeyValue

# This is an example of how to use the TimeBasedKeyValue class
# and its stop() method.

if __name__ == "__main__":
    print("Initializing the key-value store...")
    kv_store = TimeBasedKeyValue()

    print("Putting some items into the store (asynchronously)...")
    kv_store.put("foo", "v1", 10)
    kv_store.put("bar", "v2", 12)
    kv_store.put("foo", "v3", 15)

    # Give the worker thread a moment to process the items
    print("Waiting for a moment...")
    time.sleep(0.1)

    print(f"GET foo at timestamp 11: {kv_store.get('foo', 11)}")
    print(f"GET foo at timestamp 16: {kv_store.get('foo', 16)}")
    print(f"GET bar at timestamp 13: {kv_store.get('bar', 13)}")

    # --- Main application is done, time to clean up --- #
    print("\nMain program is finished. Telling the kv_store to stop...")
    kv_store.stop()

    print("Store has stopped. Exiting.")

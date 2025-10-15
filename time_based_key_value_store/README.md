# Problem: Distributed, Time-Based Key-Value Store

This system needs to handle two primary operations:

1.  `PUT(key, value, timestamp)`: Stores a `value` for a given `key` at a specific `timestamp`.
2.  `GET(key, timestamp)`: Retrieves the `value` for a given `key` as it was at a specific `timestamp`. More precisely, it should return the value associated with the latest timestamp that is less than or equal to the given `timestamp`.

## Extensions Covered

- **Concurrency:** The core data store was made thread-safe using a fine-grained, per-key locking strategy.
- **Memory Eviction:** An eviction policy was added to only store the 100 most recent values for any given key.
- **Distributed Design:** High-level design included using consistent hashing for sharding keys across multiple nodes and a stateless routing layer to direct client requests.
- **Asynchronous Operations:** The `put` method was refactored into a non-blocking operation using a background worker thread and a task queue.

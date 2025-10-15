from bisect import bisect_right, bisect_left
from collections import defaultdict
from queue import Queue
from threading import Lock, Thread


class TimeBasedKeyValue:
    def __init__(self):
        self.keyValueDict = defaultdict(lambda: [[], []])
        self.lock_dict = {}
        self.master_lock = Lock()
        
        # 1. The queue for incoming put requests
        self.task_queue = Queue()
        
        # 2. Create and start the worker thread
        self.worker_thread = Thread(target=self._worker_loop)
        self.worker_thread.daemon = True  # Use daemon=True so it doesn't block program exit
        self.worker_thread.start()

    def _worker_loop(self):
        """The main loop for the background worker thread."""
        while True:
            # 3. Get a task. This will block until a task is available.
            task = self.task_queue.get()
            
            # 4. Check for the sentinel value (None) to stop
            if task is None:
                break
            
            # 5. Unpack and process the task
            key, value, timestamp = task
            self._sync_put(key, value, timestamp)

    def _get_lock_for_key(self, key: str) -> Lock:
        with self.master_lock:
            if key not in self.lock_dict:
                self.lock_dict[key] = Lock()
            return self.lock_dict[key]

    def put(self, key: str, value: str, timestamp: int) -> None:
        """The public, asynchronous put method."""
        self.task_queue.put((key, value, timestamp))

    def stop(self):
        """Signals the worker thread to stop and waits for it to terminate."""
        self.task_queue.put(None)  # Send the sentinel value
        self.worker_thread.join()   # Wait for the thread to finish

    def _sync_put(self, key: str, value: str, timestamp: int) -> None:
        key_specific_lock = self._get_lock_for_key(key)
        with key_specific_lock:
            timestamps, values = self.keyValueDict[key]
            idx = bisect_left(timestamps, timestamp)
            timestamps.insert(idx, timestamp)
            values.insert(idx, value)
            if len(timestamps) > 100:
                self.keyValueDict[key] = [
                    timestamps[-100:],
                    values[-100:]
                ]

    def get(self, key: str, timestamp: int) -> str:
        key_specific_lock = self._get_lock_for_key(key)
        with key_specific_lock:
            timestamps, values = self.keyValueDict[key]
            if not timestamps:
                return ""
            idx = bisect_right(timestamps, timestamp)
            if idx == 0:
                return ""
            return values[idx-1]
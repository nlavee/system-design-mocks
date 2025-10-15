# Problem: Distributed Task Scheduler

Design and implement a simple distributed task scheduler.

At a high level, this system should be able to accept tasks, distribute them to a pool of workers, and allow a client to check on the status and retrieve the results of a task.

The problem is intentionally open-ended and will require asking clarifying questions to define the scope of the API, the behavior of the scheduler, the workers, and the failure modes to be handled.

## API Definition

- `add_task(func, args, kwargs)`: Submits a task for execution. Returns a unique `task_id`.
- `get_status(task_id)`: Returns the current status of the task (e.g., `QUEUED`, `PROCESSING`, `FINISHED`, `FAILED`).
- `get_result(task_id)`: Returns the result of a finished task. If the task failed, it might return the exception details. If the task is not finished, it could wait or return `None`.

## Task Definition

- A **task** is a Python function and its corresponding arguments (`args`, `kwargs`).
- A **result** is the return value of the function.
- A **failure** is when the function raises an exception.

## Final Implementation Summary

The final implementation is a thread-safe, single-process task scheduler with a pool of workers.

### Core Components:

1.  **`Scheduler` Class:** The main class that provides the public API (`add_task`, `get_status`, `get_result`). It manages all the core components.
2.  **`Task` Dataclass:** A simple data container that holds all the state for a single task, including its `task_id`, `status`, the function to execute, the final `result`, and any `exception` that occurred.
3.  **Task Queue (`queue.Queue`):** A thread-safe queue used to hold the `task_id` of tasks that are waiting to be processed.
4.  **Task Store (`dict`):** A standard dictionary that maps a `task_id` to its corresponding `Task` object. All task states are stored here.

### Architecture and Concurrency:

-   **Worker Pool:** When the `Scheduler` is initialized, it spawns a configurable number of background worker threads. These threads immediately start waiting for tasks to appear on the queue.
-   **Task Submission:** The `add_task` method creates a `Task` object, assigns it a unique ID, sets its initial status to `QUEUED`, stores it in the central `tasks` dictionary, and places the `task_id` on the queue for a worker to pick up.
-   **Concurrency Model:** A single `threading.Lock` is used to protect all read and write access to the `tasks` dictionary. This ensures that status updates from multiple workers and status reads from client threads are all thread-safe and consistent.
-   **Task Execution:** The worker gets a `task_id`, locks the dictionary to update the status to `PROCESSING`, and then **releases the lock** to execute the long-running task. After execution, it re-acquires the lock to update the dictionary with the final status and result/exception. This prevents a long-running task from blocking the entire system.
-   **Lifecycle Management:** The `stop()` method provides a graceful shutdown mechanism. It places a `None` sentinel on the queue for each worker thread, causing them to exit their loops. The main thread then `join()`s each worker to wait for it to terminate cleanly.

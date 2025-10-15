from threading import Thread, Lock, RLock
from queue import SimpleQueue
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

from exceptiongroup import catch


class TaskStatus(Enum):
    NONE = 0
    QUEUED = 1
    PROCESSING = 2
    SUCCESS = 3
    FAILED = 4


@dataclass
class TaskMetadata:
    status: TaskStatus = TaskStatus.NONE
    instruction: Any = None
    result: Any = None
    exception: Exception = None


class Scheduler:
    def __init__(self, num_workers=10):
        self.description = "Scheduler"
        self.taskQueue = SimpleQueue()

        # component to store task metadata (results, status, exception)
        self.taskMetadataLock = Lock()
        self.taskMetadata = {}

        # component to generate id
        self.idLock = Lock()
        self.latestId = 0

        # worker thread pool
        self.workerPools = []
        self.numWorker = num_workers
        # hard code to 10 workers
        for i in range(self.numWorker):
            thread = Thread(target=self._worker_task)
            self.workerPools.append(thread)
            thread.start()

    def _worker_task(self):
        while True:

            taskId, taskMetadata = self.taskQueue.get()
            if not taskId and not taskMetadata:
                return

            func, arg, krwargs = None, None, None
            # Set status that we're processing the task.
            with self.taskMetadataLock:
                if taskId not in self.taskMetadata:
                    raise Exception  # can raise another exception.
                self.taskMetadata[taskId].status = TaskStatus.PROCESSING
                func, arg, krwargs = taskMetadata.instruction

            result, exception, status = None, None, TaskStatus.FAILED
            try:
                result = func(*arg)
                status = TaskStatus.SUCCESS
            except Exception as e:
                exception = e
            finally:
                with self.taskMetadataLock:
                    taskMetadata.status = status
                    taskMetadata.exception = exception
                    taskMetadata.result = result

    def stopScheduler(self):
        for i in range(self.numWorker):
            self.taskQueue.put((None, None))
        for worker in self.workerPools:
            worker.join()

    def _generate_id(self):
        with self.idLock:
            self.latestId += 1
            return self.latestId

    def add_task(self, func, args, kwargs):
        task_id = self._generate_id()
        # 1. Set initial status to QUEUED
        taskMetadata = TaskMetadata(status=TaskStatus.QUEUED)
        taskMetadata.instruction = (func, args, kwargs)

        with self.taskMetadataLock:
            self.taskMetadata[task_id] = taskMetadata

        self.taskQueue.put((task_id, taskMetadata))
        return task_id

    def get_status(self, task_id: int) -> TaskStatus:
        with self.taskMetadataLock:
            if task_id not in self.taskMetadata:
                return TaskStatus.NONE
            return self.taskMetadata[task_id].status

    def get_result(self, task_id):
        with self.taskMetadataLock:
            if task_id not in self.taskMetadata:
                # 3. Raise KeyError for unknown task ID
                raise KeyError(f"Task ID {task_id} not found.")
            
            task = self.taskMetadata[task_id]
            # 2. If the task failed, return the exception
            if task.status == TaskStatus.FAILED:
                return task.exception
            
            # For SUCCESS or other statuses, return the result (which may be None)
            return task.result

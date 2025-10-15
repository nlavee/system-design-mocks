from time import sleep, time
import pytest
import sys
import os
from threading import Thread

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

# autopep8: off
from src.scheduler import Scheduler, TaskStatus
# autopep8: on

# --- Helper Functions for Tests ---


def successful_task(x, y):
    """A simple task that succeeds."""
    return x + y


def failing_task():
    """A simple task that fails."""
    raise ValueError("This task was meant to fail")


def long_running_task(duration):
    """A task that takes some time to run."""
    sleep(duration)
    return f"Slept for {duration} seconds"


def _wait_for_task_completion(scheduler: Scheduler, task_id: str, timeout: int = 5):
    """Polls the scheduler until a task is complete or timeout is reached."""
    start_time = time()
    while time() - start_time < timeout:
        status = scheduler.get_status(task_id)
        if status in [TaskStatus.SUCCESS, TaskStatus.FAILED]:
            return
        sleep(0.05)
    raise TimeoutError(
        f"Task {task_id} did not complete within {timeout} seconds.")

# --- Test Suite ---


@pytest.fixture
def scheduler():
    """Pytest fixture to create and properly stop the Scheduler for each test."""
    s = Scheduler(num_workers=10)
    yield s
    s.stopScheduler()


class TestScheduler:

    def test_add_and_get_successful_task(self, scheduler):
        """Tests the full lifecycle of a successful task."""
        task_id = scheduler.add_task(successful_task, args=[5, 10], kwargs={})

        assert scheduler.get_status(task_id) == TaskStatus.QUEUED

        _wait_for_task_completion(scheduler, task_id)

        assert scheduler.get_status(task_id) == TaskStatus.SUCCESS
        assert scheduler.get_result(task_id) == 15

    def test_add_and_get_failing_task(self, scheduler):
        """Tests the full lifecycle of a failing task."""
        task_id = scheduler.add_task(failing_task, args=[], kwargs={})

        _wait_for_task_completion(scheduler, task_id)

        assert scheduler.get_status(task_id) == TaskStatus.FAILED
        result = scheduler.get_result(task_id)
        assert isinstance(result, ValueError)
        assert str(result) == "This task was meant to fail"

    def test_get_non_existent_task(self, scheduler):
        """Tests that getting status/result for a fake task ID behaves correctly."""
        assert scheduler.get_status("fake-id") == TaskStatus.NONE
        with pytest.raises(KeyError):
            scheduler.get_result("fake-id")

    def test_concurrency_and_stress(self, scheduler):
        """Submits many tasks from multiple threads to test concurrent execution."""
        num_threads = 10
        tasks_per_thread = 20
        total_tasks = num_threads * tasks_per_thread
        threads = []
        task_ids = []

        def submit_tasks():
            for i in range(tasks_per_thread):
                # Mix of success and failure tasks
                if i % 4 == 0:
                    task_id = scheduler.add_task(
                        failing_task, args=[], kwargs={})
                else:
                    task_id = scheduler.add_task(
                        successful_task, args=[i, i], kwargs={})
                task_ids.append(task_id)

        for _ in range(num_threads):
            thread = Thread(target=submit_tasks)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()  # Wait for all threads to finish submitting tasks

        # Wait for the last submitted task to complete
        _wait_for_task_completion(scheduler, task_ids[-1])

        # --- Verification ---
        success_count = 0
        failed_count = 0
        for task_id in task_ids:
            status = scheduler.get_status(task_id)
            assert status in [TaskStatus.SUCCESS, TaskStatus.FAILED]
            if status == TaskStatus.SUCCESS:
                success_count += 1
            else:
                failed_count += 1

        assert len(task_ids) == total_tasks
        assert success_count == 150  # 3/4 of 200
        assert failed_count == 50  # 1/4 of 200

import glob
import logging
import os
from multiprocessing import Pool
from functools import partial
from typing import Callable, List, Dict, Any, Iterable, TypeVar

# --- Type Variables for Generic Functions ---
T = TypeVar('T') # Represents an intermediate result type (e.g., a dict or Counter)
R = TypeVar('R') # Represents the final aggregated result type

# --- Configure Logging for Observability ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(processName)s - %(levelname)s - %(message)s'
)

# --- Worker Function (Must be at the top level for pickling) ---

def _process_file_wrapper(filepath: str, process_func: Callable[[str], T]) -> T | None:
    """
    Reads a single file and processes its content using the provided function.

    This wrapper includes error handling to ensure that a single malformed file
    does not crash the entire processing pipeline.

    Args:
        filepath: The absolute path to the file to process.
        process_func: The CPU-intensive function to apply to the file's content.

    Returns:
        The result of the processing function, or None if an error occurred.
    """
    try:
        logging.info(f"Processing file: {filepath}")
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return process_func(content)
    except Exception as e:
        logging.error(f"Failed to process file {filepath}: {e}")
        return None

# --- Main Processor Class ---

class ParallelDataProcessor:
    """
    Processes a large number of text files in a directory in parallel.

    This class demonstrates a robust pattern for single-machine, multi-core,
    CPU-bound parallel processing in Python. It uses a `multiprocessing.Pool`
    to bypass the Global Interpreter Lock (GIL) and achieve true parallelism.

    The design is analogous to distributed systems like Spark:
    - The list of files acts as the set of data partitions.
    - The worker processes in the pool are like Spark executors.
    - The aggregation of results is equivalent to a shuffle/reduce phase.
    """

    def __init__(self, num_workers: int | None = None):
        """
        Initializes the data processor.

        Args:
            num_workers: The number of worker processes to spawn.
                         Defaults to the number of logical CPU cores, which is
                         optimal for CPU-bound tasks.
        """
        self.num_workers = num_workers or os.cpu_count()
        logging.info(f"Initialized processor with {self.num_workers} worker processes.")

    def process_directory(
        self,
        dir_path: str,
        process_func: Callable[[str], T],
        aggregator_func: Callable[[R, T], R],
        initial_value: R
    ) -> R:
        """
        Discovers .txt files, processes them in parallel, and aggregates the results.

        Args:
            dir_path: The path to the directory containing .txt files.
            process_func: A function that takes file content (str) and returns an
                          intermediate result of type T.
            aggregator_func: A function that merges an intermediate result (T) into
                             the running total (R).
            initial_value: The starting value for the aggregation.

        Returns:
            The final aggregated result of type R.
        """
        filepaths = glob.glob(os.path.join(dir_path, "*.txt"))
        if not filepaths:
            logging.warning(f"No .txt files found in directory: {dir_path}")
            return initial_value

        logging.info(f"Found {len(filepaths)} files to process.")

        # `functools.partial` is used to create a new function with the
        # `process_func` argument "baked in". This is a clean and efficient
        # way to pass fixed arguments to a map function in multiprocessing.
        task = partial(_process_file_wrapper, process_func=process_func)

        final_result: R = initial_value
        with Pool(processes=self.num_workers) as pool:
            # Justification for `imap_unordered`:
            # This method is chosen for memory efficiency and performance.
            # 1. It's an iterator (`i` map), so results are processed as they
            #    complete, rather than all at once. This prevents all intermediate
            #    results from being stored in memory, which is crucial for large
            #    datasets.
            # 2. It's `unordered`, meaning results are yielded as soon as a worker
            #    finishes, not in the order of the input. This maximizes throughput.
            results_iterator = pool.imap_unordered(task, filepaths)

            for intermediate_result in results_iterator:
                if intermediate_result is not None:
                    final_result = aggregator_func(final_result, intermediate_result)

        logging.info("All files have been processed and results aggregated.")
        return final_result
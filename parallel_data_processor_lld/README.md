# LLD Challenge: A Parallel Data Processor

## Problem Category: Concurrency & Parallel Computing

## Problem Description

Design a Python application that processes a large number of text files from a directory in parallel to generate an aggregated result. For this exercise, we will use a word count as the example aggregation, but the design should be generic enough to support other types of processing.

This problem focuses on leveraging multiple CPU cores to complete a CPU-bound task efficiently on a single machine.

### Core Requirements

1.  **Input:** The application takes a path to a directory containing potentially thousands of `.txt` files.
2.  **Processing:** It applies a function to the content of each file. This function performs a CPU-intensive task, such as calculating word frequencies, and returns an intermediate result (e.g., a `dict` mapping words to their counts).
3.  **Parallelism:** The core requirement is that multiple files must be processed simultaneously, making full use of the available CPU cores on the machine.
4.  **Aggregation:** The intermediate results from all the parallel workers must be combined into a single, final aggregated result (e.g., a final dictionary containing the total word counts across all files).

### LLD Focus & Evaluation Criteria

*   **Concurrency Model Justification:** The central task is to justify your choice of concurrency model. Why is `multiprocessing` the correct tool for this job, as opposed to `threading` or `asyncio`? Your explanation should demonstrate a clear understanding of Python's Global Interpreter Lock (GIL) and the difference between CPU-bound and I/O-bound work.

*   **Work Distribution:** Your design should use a `multiprocessing.Pool` or a similar robust mechanism to manage a pool of worker processes and distribute the file-processing tasks among them.

*   **Result Aggregation (The Core Challenge):** This is the most critical part of the design. Worker processes have separate memory spaces. How do you safely and efficiently collect the intermediate results (e.g., many dictionaries) from all the workers and combine them into one final result in the main process? You must discuss the trade-offs between different Inter-Process Communication (IPC) strategies:
    *   Returning results directly from the pool's `map`/`apply` functions.
    *   Using a shared `multiprocessing.Queue`.
    *   Using a `multiprocessing.Manager` to create a shared dictionary or list.

*   **Error Handling & Robustness:** What happens if a worker process crashes while processing a malformed file? How does the main process handle this without stalling indefinitely?

### The Databricks Edge: Analogy to Distributed Computing

A Staff-level discussion must connect this single-machine parallel processing problem to the architecture of a large-scale distributed computing system like Apache Spark.

*   **Analogies:** You should be able to draw direct parallels:
    *   **Files** -> **Data Partitions** in an RDD or DataFrame.
    *   **Worker Processes** -> **Spark Executors** running tasks on different nodes in a cluster.
    *   **Result Aggregation** -> A **Shuffle and Reduce** phase in Spark (e.g., for a `reduceByKey` or `groupBy` operation).

*   **Scaling Challenges:** Discuss how the challenges of result aggregation on a single machine (IPC, serialization, memory) become magnified in a distributed environment. This should lead to a discussion of network I/O bottlenecks, data serialization formats, and memory management on executors, which are all core challenges in designing and optimizing Spark jobs.

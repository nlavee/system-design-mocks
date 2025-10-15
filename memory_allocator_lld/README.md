# LLD Challenge: Design a Memory Allocator

## Problem Category: Robust Utility Component

## Problem Description

Design a low-level memory allocator that manages a large, contiguous block of memory. The component must provide the functionality to allocate and free chunks of memory, similar to the standard C library functions `malloc()` and `free()`.

This is a deep, infrastructure-focused problem that tests your understanding of low-level data structures, memory management, and algorithmic trade-offs. The goal is to design a component that is both correct and efficient.

### Core Requirements

1.  **Memory Management:** The allocator will be initialized with a single, large, contiguous block of memory (e.g., a byte array).
2.  **Allocation:** It must expose a method, `allocate(size: int)`, which finds a suitable free chunk of memory, marks it as allocated, and returns a "pointer" or handle to it. If no suitable block is found, it should indicate failure (e.g., return null or raise an exception).
3.  **Deallocation:** It must expose a method, `free(pointer)`, which takes a handle to a previously allocated block and marks it as free, making it available for future allocations.
4.  **Efficiency:** The allocator must be efficient and aim to minimize memory fragmentation. This means it should try to avoid leaving many small, unusable gaps between allocated blocks.

### LLD Focus & Evaluation Criteria

*   **Data Structures:** The core of the design is the data structure used to track free memory blocks. A common and effective choice is a **doubly linked list** of free blocks. Your ability to describe and manage this data structure is critical.
*   **Strategy Pattern:** The algorithm used to select a free block can be abstracted. You should use the **Strategy Pattern** to define an `AllocationStrategy` interface with concrete implementations like:
    *   `FirstFit`: Scans the free list from the beginning and chooses the first block that is large enough.
    *   `BestFit`: Scans the entire free list to find the smallest block that is large enough, minimizing wasted space for that allocation.
    *   `WorstFit`: Finds the largest available block, which tends to leave large, more useful leftover chunks.
*   **Meticulous Logic:** The implementation requires careful handling of block splitting (when an allocated chunk is smaller than the free block it came from) and coalescing (when a freed block is adjacent to other free blocks, they should be merged into a single, larger free block).

### The Databricks Edge: Executor Memory Management

This problem is a direct microcosm of the memory management challenges within a Spark executor or a database engine. A Staff-level discussion must connect the design to this context. Be prepared to answer:

*   **Fragmentation Impact:** How does memory fragmentation affect the performance and stability of long-running, data-intensive Spark jobs? Why is an efficient allocator critical in this environment?
*   **Concurrency:** In a Spark worker node, multiple tasks run in parallel on different threads. How would you make your memory allocator thread-safe? A single, global lock on `allocate` and `free` would be a major performance bottleneck. This leads to a discussion of more advanced techniques like thread-local allocation pools or lock-free data structures.
*   **Garbage Collection:** How does a managed memory system (like the JVM or Python interpreter) interact with this kind of low-level allocation? How does this relate to Spark's own off-heap memory management (Project Tungsten)?

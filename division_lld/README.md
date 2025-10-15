# LLD Case Study: Implement Division

## Problem Description

Design a low-level utility component that performs robust integer division, returning a quotient and a remainder. The key constraint is that you **cannot** use the native language division or modulo operators (`/`, `//`, `%`). Instead, the calculation must be based on a provided abstract set of assembly-like instructions.

This is an exercise in architectural rigor, attention to detail, and designing for extensibility. The goal is to model a component suitable for core infrastructure, like an optimized query execution engine (e.g., Spark's Photon engine).

### Core Requirements

1.  **Abstraction:** The main division logic must be decoupled from the underlying calculation method. It should be possible to switch out the calculation strategy (e.g., from a binary bit-shifting implementation to a simple repeated-subtraction implementation) without changing the main component.
2.  **Robustness & Edge Cases:** The component must handle all edge cases gracefully, including:
    *   Division by zero.
    *   Correct sign handling for positive and negative operands.
    *   Large numbers (within standard integer limits).
3.  **Clarity and Testability:** The design must be highly modular and testable, with clear separation of concerns.

### Evaluation Criteria

*   **Application of SOLID Principles:** The design must heavily leverage the Dependency Inversion Principle (DIP) and the Open/Closed Principle (OCP).
*   **Use of Design Patterns:** The Strategy pattern is fundamental to meeting the abstraction requirement.
*   **Code Quality:** The implementation should be clean, with immutable value objects and custom exceptions for clear error handling.
*   **Attention to Detail:** The solution must demonstrate a meticulous approach to numerical calculation and edge case management.

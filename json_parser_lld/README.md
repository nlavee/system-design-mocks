# LLD Challenge: Design a JSON Parser

## Problem Category: Robust Utility Component

## Problem Description

Design and implement a component that can parse a UTF-8 string into a structured JSON object. A key constraint is that you **cannot** use any built-in or third-party JSON parsing libraries (e.g., Python's `json` module).

This problem tests your ability to design a robust, low-level utility, focusing on parsing logic, error handling, and creating a clean in-memory representation of the parsed data.

### Core Requirements

1.  **Full JSON Support:** The parser must correctly handle all standard JSON data types:
    *   Objects (`{}`)
    *   Arrays (`[]`)
    *   Strings (in double quotes, with support for basic escape sequences like `\"`)
    *   Numbers (integers and floating-point)
    *   Booleans (`true`, `false`)
    *   `null`
2.  **Nested Structures:** The parser must be able to handle arbitrarily nested objects and arrays.
3.  **Error Handling:** The parser must be robust. It should throw a specific, informative exception (e.g., `MalformedJsonException`) when it encounters invalid syntax, indicating where the error occurred if possible.

### LLD Focus & Evaluation Criteria

*   **Parsing Logic:** The core of the evaluation is the parsing algorithm itself. A common approach is a **recursive descent parser**, where different functions are responsible for parsing different types (e.g., `parse_object`, `parse_array`, `parse_string`). The logic must be clean and easy to follow.
*   **Object Model:** You should design a clean set of classes to represent the parsed JSON in memory (e.g., `JsonObject`, `JsonArray`, `JsonString`, etc.). This demonstrates your ability to model data structures.
*   **Robustness:** Meticulous handling of edge cases (e.g., trailing commas, unclosed brackets, invalid escape sequences) and clear, specific error handling are critical.

### The System Design Edge: Large-Scale Data Processing

A Staff-level discussion must address how this component would function in a big data environment. Be prepared to answer:

*   **Streaming Parser:** Your initial design will likely load the entire string into memory. How would you re-design your parser to handle a 50 GB JSON file that cannot fit on a single machine? This requires evolving the design into a **streaming parser** (or token-based parser), which reads the input stream character by character and emits tokens or builds the object incrementally, without holding the entire file in memory. This is directly analogous to how Spark and other data systems process massive files.
*   **Performance:** In a streaming context, what are the performance bottlenecks? How could you optimize the parser for speed? (e.g., efficient string handling, minimizing object allocations).


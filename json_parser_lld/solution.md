# LLD Solution: JSON Parser

This document outlines the design for a JSON parser built from scratch, focusing on robustness, a clean object model, and a design that can be extended to handle large-scale data streams.

---

## Part 1: LLD Implementation Plan for an In-Memory Parser

### 1. Core Philosophy: Tokenizer + Recursive Descent Parser

A robust parser is best designed in two distinct stages, adhering to the Single Responsibility Principle:

1.  **Tokenizing (Lexical Analysis):** The first stage scans the raw input string and breaks it into a sequence of indivisible tokens (e.g., `{`, `}`, `"a string"`, `123`, `true`). This component, the `Tokenizer`, handles the low-level details of character-by-character scanning and skipping whitespace.

2.  **Parsing (Syntax Analysis):** The second stage, the `Parser`, takes the stream of tokens from the `Tokenizer` and builds a logical structure from them. It doesn't care about whitespace or character-level syntax; it only thinks in terms of tokens.

We will use a **Recursive Descent** approach for the parser. This is a natural and intuitive strategy where the structure of the code mirrors the hierarchical grammar of JSON. We will have a set of mutually recursive methods, each responsible for parsing a specific part of the grammar (e.g., `_parse_object`, `_parse_array`).

### 2. Component Breakdown (SRP)

*   **`Tokenizer` (Lexer):**
    *   **Responsibility:** To convert an input string into a stream of `Token` objects.
    *   **Implementation:** It maintains a pointer to the current position in the string. It has methods to peek at the next character and advance the pointer. It can identify and construct tokens for left/right braces, left/right brackets, commas, colons, strings, numbers, booleans, and nulls.

*   **`Parser`:**
    *   **Responsibility:** To consume tokens from the `Tokenizer` and build the final Python object representation of the JSON structure.
    *   **Implementation:** It holds an instance of the `Tokenizer`. Its main `parse()` method checks the first token to decide which specific parsing method to call (e.g., if it sees a `{`, it calls `_parse_object()`). The `_parse_object` method will then recursively call `parse()` to parse the values within that object, leading to the recursive descent.

*   **`Token` and `TokenType` (Models):**
    *   **Responsibility:** To serve as a simple data structure for passing information from the `Tokenizer` to the `Parser`.
    *   **Implementation:** `TokenType` will be an `Enum` with members like `LEFT_BRACE`, `STRING`, `NUMBER`, etc. `Token` will be a simple dataclass containing a `type` and a `value`.

*   **`JsonParseException` (Exception):**
    *   **Responsibility:** To provide clear, informative errors when parsing fails.
    *   **Implementation:** A custom exception class that can optionally include the line and column number to help users debug malformed JSON.

### 3. Execution Flow (Example: Parsing `{"key": 123}`)

1.  The `Parser` is initialized with the string `"{\"key\": 123}"`.
2.  The `Parser`'s main `parse()` method asks the `Tokenizer` for the first token. The `Tokenizer` returns a `Token(TokenType.LEFT_BRACE, '{')`.
3.  Seeing a `LEFT_BRACE`, the `Parser` calls its `_parse_object()` method.
4.  `_parse_object()` expects a `STRING` token for the key. It asks the `Tokenizer`, which returns `Token(TokenType.STRING, 'key')`.
5.  `_parse_object()` then expects a `COLON`. The `Tokenizer` returns `Token(TokenType.COLON, ':')`.
6.  `_parse_object()` now needs to parse the value. It recursively calls the main `parse()` method.
7.  The main `parse()` method asks the `Tokenizer` for the next token, which is `Token(TokenType.NUMBER, 123)`.
8.  `parse()` sees a `NUMBER` token and simply returns the value `123`.
9.  Control returns to `_parse_object()`. It now has the key (`'key'`) and the value (`123`). It continues this process until it sees a `RIGHT_BRACE` token from the `Tokenizer`.
10. Finally, `_parse_object()` returns the complete dictionary `{'key': 123}`.

---

## Part 2: Solutions for "The Databricks Edge"

### 1. Streaming Parser for Large-Scale Data

**Problem:** The in-memory design, which takes the full string as input, will fail for a 50 GB JSON file.

**Solution:** The key is to evolve the design into a **streaming parser**. Our two-component architecture (`Tokenizer` + `Parser`) makes this change remarkably elegant.

1.  **Modify the `Tokenizer`:** Instead of accepting a string in its constructor, the `StreamingTokenizer` will accept a **file-like object** (an I/O stream).
2.  **Change Internal Logic:** The `StreamingTokenizer` will no longer have the full content available. It will read from the stream character-by-character (or, more efficiently, using a small internal buffer of a few kilobytes). Its responsibility remains the same: to yield a stream of tokens. The only difference is its input source.
3.  **No Change to the `Parser`:** The `Parser` is already designed to work with an iterator of tokens. It doesn't care whether the `Tokenizer` generated those tokens from an in-memory string or a massive file stream. This demonstrates the immense value of the decoupled design.

This streaming approach is directly analogous to how Spark processes massive files. It reads data in partitions or streams, never requiring a single worker node to load the entire dataset into memory.

### 2. Performance in a Streaming Context

**Problem:** In a high-throughput streaming environment, what are the performance bottlenecks and how can they be optimized?

**Bottlenecks:**
*   **I/O Operations:** Reading from disk or network is always the slowest part. Reading one character at a time is highly inefficient due to the overhead of system calls.
*   **String/Object Allocation:** For a JSON file representing tabular data (e.g., an array of millions of small objects), the creation of millions of Python dictionary objects can be a major CPU and memory bottleneck, putting pressure on the garbage collector.

**Optimizations:**
1.  **Buffered I/O:** The `StreamingTokenizer` should not read one character at a time from the stream. It should read in larger, fixed-size chunks (e.g., 4KB or 8KB) into an internal buffer. It then processes characters from this buffer. When the buffer is exhausted, it reads the next chunk from the stream. This drastically reduces the number of expensive I/O system calls.

2.  **Schema-Aware Tabular Conversion (Advanced):** For the use case of a large array of objects, a Staff-level parser could be designed to be "schema-aware." Instead of creating millions of Python dictionaries, if the parser detects this structure, it could be configured to directly serialize the data into a highly efficient, columnar in-memory format like **Apache Arrow** or a **Pandas DataFrame**. This bypasses the overhead of intermediate Python object creation and is a technique used in modern data systems like Databricks to accelerate data loading and processing.

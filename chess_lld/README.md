# LLD Case Study: Implement Chess

## Problem Description

Design the core back-end components for a game of chess. The primary goal is to create a clean, extensible, and robust object model that manages game state, enforces rules, and processes moves.

This is a Low-Level Design (LLD) exercise. The focus is on architectural quality, not on creating a playable UI or a chess-playing AI (e.g., a minimax algorithm).

### Core Requirements

1.  **State Management:** The system must accurately represent the board, the pieces, and the overall game state (e.g., whose turn it is, game history).
2.  **Rule Enforcement:** The system must correctly enforce all rules of chess, including:
    *   Basic piece movements (Pawn, Rook, Knight, Bishop, Queen, King).
    *   Complex rules like check, checkmate, and stalemate.
    *   Special moves such as castling and en passant.
3.  **Extensibility:** The design should be modular and extensible, allowing for new rules or even new chess variants to be added with minimal changes to the core system (adhering to the Open/Closed Principle).
4.  **Concurrency & Data Integrity (The Databricks Edge):** The design must consider a scenario where game states might be accessed or simulated concurrently. The solution should incorporate principles that ensure thread safety and maintain a reliable, auditable history of moves, similar to the transaction logs in systems like Delta Lake.

### Evaluation Criteria

*   **Clarity of Class Design:** Adherence to SOLID principles, especially the Single Responsibility Principle (SRP).
*   **Use of Design Patterns:** Effective use of patterns like Strategy for rule validation.
*   **Handling of State:** Robust management of the game's complex, stateful nature.
*   **Concurrency & Reliability:** A clear strategy for handling concurrent reads/writes and ensuring data integrity.

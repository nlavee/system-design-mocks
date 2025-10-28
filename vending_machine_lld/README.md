# LLD Challenge: Design a Vending Machine

## Problem Category: Complex System Logic & State Management

## Problem Description

Design the back-end software for a networked vending machine. The system must manage inventory, handle transactions, and interact with users through a simple interface. The core of this problem lies in managing the machine's various states in a clean and robust way.

### Core Requirements

1.  **Item Management:** The machine should have a configurable inventory of items, each with a name, price, and quantity.
2.  **Stateful Operation:** The machine must operate in several distinct states. At a minimum, it should support:
    *   `IdleState`: Waiting for a user to start a transaction.
    *   `AcceptingMoneyState`: The user has selected an item and is inserting money.
    *   `DispensingState`: The machine is dispensing the item and calculating change.
    *   `SoldOutState`: The selected item is out of stock.
3.  **Transaction Handling:** The machine must be able to accept money, validate if the amount is sufficient, and provide correct change.
4.  **User Interaction:** Assume simple methods exist to get user input (e.g., `item_selected(item_id)`, `money_inserted(amount)`) and to provide output (e.g., `display_message(message)`).

### LLD Focus & Evaluation Criteria

*   **State Pattern:** The primary evaluation criteria is your ability to use the **State Pattern** effectively to manage the machine's lifecycle. The goal is to avoid a massive `if/else` block in a single `VendingMachine` class. Each state should be an object that handles the logic specific to that state.
*   **Single Responsibility Principle (SRP):** Your design should feature clear separation of concerns. For example, you should have distinct components like an `InventoryManager` (handles item stock), a `PaymentProcessor` (handles money), and the core `VendingMachine` (manages state).
*   **Extensibility:** The design should be easy to extend. For example, adding a new payment method (like a credit card) should be possible without rewriting the entire system.

### The System Design Edge: Concurrency & Distributed Systems

A Staff-level discussion must address the problem of scale. Be prepared to answer:

*   **Fleet Management:** How would you design the software to support a fleet of 10,000 machines? How does a central server receive real-time inventory data from all machines?
*   **Data Synchronization:** How do you push updates (e.g., price changes, new items) from the central server to the machines? What happens if a machine is temporarily offline (e.g., loses network connectivity)? How does it sync up when it comes back online?
*   **Concurrency:** The central server will be receiving updates from thousands of machines concurrently. How do you design the server-side API and database schema to handle this high-write workload efficiently?

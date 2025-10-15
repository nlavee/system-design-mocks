# This file serves as a design document and study guide for the Vending Machine LLD.
# It explains the implementation plan for the single-machine solution and provides
# detailed architectural solutions for the distributed system challenges.

"""
Part 1: LLD Implementation Plan for a Single Vending Machine

This section details the design choices made in the implementation, focusing on the
State Pattern and the Single Responsibility Principle (SRP) as mandated by the LLD criteria.

**1. Core Philosophy: The State Pattern**

The primary challenge of a vending machine is managing its complex, stateful nature. A naive
approach would place all logic inside the `VendingMachine` class, resulting in a large and
brittle `if/else` structure (e.g., `if self.state == 'idle': ... elif self.state == 'accepting_money': ...`).

To avoid this, we use the **State Pattern**. The core idea is to represent each state of the
machine as a distinct object. The main `VendingMachine` class (the "Context") holds a
reference to its current state object and delegates all actions to it. When an action
occurs (like inserting money), the current state object handles the logic and tells the
`VendingMachine` which state to transition to next. This makes the `VendingMachine` class
stable and simple, and all logic for a specific state is cleanly encapsulated in its own class.

**2. Component Breakdown (Single Responsibility Principle)**

To ensure the design is modular and maintainable, responsibilities are separated into distinct components:

*   `VendingMachine` (The Context):
    *   **Responsibility:** To maintain the machine's context. It holds the current state (`self.state`)
      and references to shared components (`InventoryManager`, `PaymentProcessor`).
    *   **Implementation:** It does no logic itself. All user actions (`select_item`, `insert_money`)
      are delegated directly to the current state object (e.g., `self.state.select_item(...)`).
      It exposes a `change_state()` method that allows state objects to transition the machine.

*   `State` (The State Interface & Concrete Implementations):
    *   **Responsibility:** The `State` abstract base class defines the interface that all states must
      implement (e.g., `select_item`, `insert_money`). This ensures interchangeability.
    *   **Implementation:** Each concrete state (`IdleState`, `AcceptingMoneyState`, `DispensingState`,
      `SoldOutState`) implements the methods of the `State` interface. For example, `IdleState.select_item()`
      will check inventory and transition to `AcceptingMoneyState`, while `DispensingState.select_item()`
      will raise an `InvalidOperationException` because you can't select an item while another is dispensing.

*   `InventoryManager`:
    *   **Responsibility:** To encapsulate all logic related to item stock. This includes getting items,
      checking stock levels, and dispensing (reducing stock).
    *   **Implementation:** It uses a dictionary to store `Item` objects, keyed by `item_id`. Storing the
      full, immutable `Item` object is more robust than using raw dictionaries, preventing errors
      from typos in string keys (e.g., `['qty']` vs `['quantity']`).

*   `PaymentProcessor` (The Strategy):
    *   **Responsibility:** To abstract the process of handling payments. This allows the vending machine
      to support different payment methods without changing its core logic.
    *   **Implementation:** It is defined as an abstract base class, making it a perfect example of the
      **Strategy Pattern**. We provide a `CashPaymentProcessor` as one concrete strategy. A
      `CreditCardPaymentProcessor` could be easily added later and injected into the `VendingMachine`
      with no other code changes, fulfilling the Open/Closed Principle.

*   `Models` and `Exceptions`:
    *   **Responsibility:** To provide clear, robust data structures and error types.
    *   **Implementation:** We use immutable `dataclass(frozen=True)` for `Item` to prevent accidental
      state modification. We define a hierarchy of custom exceptions (`ItemNotFoundException`,
      `InsufficientFundsException`) to allow for specific and clear error handling.

**3. Execution Flow (Example: Successful Purchase)**

1.  **Initial State:** `VendingMachine` starts in `IdleState`.
2.  **User Action:** `machine.select_item("101")` is called.
3.  **Delegation:** `VendingMachine` delegates the call to `IdleState.select_item()`.
4.  **State Logic:** `IdleState` checks the inventory. It finds the item is in stock.
5.  **State Transition:** `IdleState` calls `machine.change_state(AcceptingMoneyState(machine))`.
6.  **User Action:** `machine.insert_money(1.50)` is called.
7.  **Delegation:** `VendingMachine` delegates the call to the *new* state, `AcceptingMoneyState.insert_money()`.
8.  **State Logic:** `AcceptingMoneyState` sees that enough money has been inserted.
9.  **State Transition:** It calls `machine.change_state(DispensingState(machine))` and immediately calls `dispense_item()` on the new state.
10. **Final State Logic:** `DispensingState` tells the `InventoryManager` to reduce stock, tells the
    `PaymentProcessor` to finalize the transaction, and finally calls `machine.change_state(IdleState(machine))`
    to return the machine to its initial state, ready for the next customer.

"""

"""
Part 2: Solutions for "The Databricks Edge" (Distributed System Design)

This section provides high-level architectural solutions for managing a fleet of 10,000
networked vending machines, as per the `README.md` edge questions.

**1. Fleet Management & Data Synchronization**

**Architecture:** We will use a **Client-Server** model. The vending machines are the clients, and a central
`VendingCloudService` is the server.

**Communication Protocol:**
*   Communication will be over **HTTPS** using a **RESTful API** for simplicity and standard network traversal.
*   Each machine will have a unique `machine_id` and an API key for authentication.

**Data Flow & Offline Support:**
1.  **Heartbeat/Sync:** Each vending machine will send a `POST /api/v1/machines/{machine_id}/sync` request to the cloud service on a regular interval (e.g., every 5 minutes) and also after every transaction. This request payload will be a batch of all transactions (sales, errors) that have occurred since the last successful sync. This batching mechanism is critical for **offline support**; if the machine loses connectivity, it continues to operate locally and simply builds up a larger batch to send when it comes back online.

    ```json
    // Example POST /sync payload
    {
      "last_sync_ts": "2025-10-12T10:00:00Z",
      "config_version": "v1.2",
      "transactions": [
        { "ts": "2025-10-12T10:01:30Z", "item_id": "101", "price_paid": 1.50 },
        { "ts": "2025-10-12T10:03:15Z", "item_id": "102", "price_paid": 1.00 }
      ],
      "inventory_levels": {
        "101": 3,
        "102": 8
      }
    }
    ```

2.  **Configuration Management:** The cloud service needs to push updates (prices, new items) to the machines. The response to the `/sync` request is the perfect vehicle for this. The server checks the `config_version` sent by the machine. If it's outdated, the server includes the new configuration in the response body. The machine is then responsible for applying this new configuration locally.

    ```json
    // Example /sync response with a config update
    {
      "status": "success",
      "new_config": {
        "version": "v1.3",
        "items": [
          { "item_id": "101", "name": "Cola", "price": 1.75, "quantity": 5 },
          { "item_id": "205", "name": "Water", "price": 1.25, "quantity": 15 }
        ]
      }
    }
    ```

**2. Concurrency: Handling High-Write Workload on the Server**

**Problem:** A fleet of 10,000 machines sending sync requests concurrently will overwhelm a traditional database with direct writes.

**Architecture:** We will use an **asynchronous, queue-based ingestion architecture** to decouple the API from the database.

1.  **API Gateway & Ingestion Queue:** The `POST /sync` requests from the machines will first hit a highly scalable API Gateway. Instead of writing to a database, the API endpoint's only job is to perform authentication, validate the request format, and then publish the entire payload as a message to a message queue (e.g., **AWS SQS** or **Apache Kafka**). This is an extremely fast, low-latency operation.

2.  **Asynchronous Workers:** A pool of stateless worker services (e.g., **AWS Lambda functions** or a containerized service on Kubernetes) will read messages from the queue in parallel. Each worker processes one transaction batch at a time. Its job is to parse the message, update the inventory counts, and record the transactions in the main database.

3.  **Database Choice & Schema:**
    *   **Database:** A **NoSQL database** like **Amazon DynamoDB** or **Cassandra** is ideal for this workload. These databases are designed for high-write throughput and horizontal scaling.
    *   **Schema/Partitioning:** The primary data table (e.g., `MachineInventory`) would use the `machine_id` as its **partition key**. This ensures that all updates for a single machine go to the same physical partition in the database, preventing hotspots and distributing the write load evenly across the entire cluster as the fleet grows.

This architecture is highly scalable and resilient. The message queue acts as a massive buffer, absorbing spikes in traffic. The decoupled workers can be scaled up or down based on the queue depth, and the partitioned NoSQL database can handle the high-volume writes efficiently.
"""

print("Solution and design document created at vending_machine_lld/solutions.py")

# LLD Solution: Library Management System

This document outlines the design for a library management system, focusing on a clean object model, the use of behavioral design patterns for extensibility, and architectural solutions for distributed system challenges.

---

## Part 1: LLD Implementation Plan for a Single-Branch Library

### 1. Core Philosophy: Service-Oriented with a Rich Domain Model

The design is centered around a rich **Domain Model**, where classes like `Book`, `Member`, and `Loan` represent real-world entities. However, the core business logic (e.g., checking out a book) is not placed on these models. Instead, it is encapsulated in **Service Classes** (`BorrowingService`). This approach provides a clear separation of concerns (SRP): the models hold data and state, while the services orchestrate complex operations.

This design makes the system highly testable and modular. We also heavily leverage behavioral design patterns to manage complex and changing business rules.

### 2. Component Breakdown (SRP & Design Patterns)

*   **Domain Models:**
    *   `Book`: Represents the abstract concept of a book (ISBN, title). It also acts as the **Subject** in the Observer pattern, maintaining a list of members who have reserved it.
    *   `BookCopy`: Represents a physical copy of a `Book`. It has a unique ID and a status (`AVAILABLE`, `LOANED`).
    *   `Member`: Represents a user. This is a good candidate for an abstract class, with `Student` and `Faculty` as concrete types. It acts as the **Observer**.
    *   `Loan`: A value object linking a `Member` to a `BookCopy`, containing the checkout and due dates.

*   **Service Classes:**
    *   `BorrowingService`: The primary orchestrator for all business logic. It handles `checkout_book`, `return_book`, and `reserve_book`. It uses the Strategy and Observer patterns to perform its duties.

*   **Strategy Pattern for Business Rules:**
    *   **Problem:** Different member types have different rules for loan durations and fines. Hard-coding this in the `BorrowingService` would violate the Open/Closed Principle (OCP).
    *   **Solution:** We define a `BorrowingPolicy` interface (the **Strategy**). This interface has methods like `get_loan_duration()` and `calculate_fine()`. We create concrete strategies (`StudentPolicy`, `FacultyPolicy`) that implement this interface. The `BorrowingService` is given the correct policy for a member and uses it to enforce rules, without needing to know the member's specific type.

*   **Observer Pattern for Reservations:**
    *   **Problem:** When a book is returned, members who have reserved it must be notified.
    *   **Solution:** The `Book` model acts as the **Subject**. It maintains a list of `Member` objects (the **Observers**). When a copy of the book is returned, the `BorrowingService` calls `book.notify_observers()`. The `Book` then iterates through its list of observers and calls their `update()` method, which would trigger a notification (e.g., sending an email).

### 3. Execution Flow (Example: Returning a Reserved Book)

1.  A user returns a `BookCopy`. The `BorrowingService.return_book()` method is called.
2.  The service updates the `BookCopy` status to `AVAILABLE` and closes the `Loan`.
3.  The service retrieves the abstract `Book` associated with the returned copy.
4.  It calls `book.notify_observers()`.
5.  The `Book` object iterates through its list of registered `Member` observers.
6.  For each `Member`, it calls `member.update(book)`. The `Member` object would then contain the logic to handle the notification (e.g., "The book you reserved, 'The Great Gatsby', is now available!").

---

## Part 2: Solutions for "The Databricks Edge"

### 1. Distributed Catalog for Multiple Branches

**Problem:** The system must support multiple libraries, and users need a unified, real-time view of book availability across all locations.

**Solution:** The architecture moves from a single application instance to a **centralized database model**.

1.  **Central Database:** All branches connect to a single, master database. The `BookCopy` table/collection is modified to include a `branch_id` column.
2.  **Real-Time Search:** When a user searches for a book, the query is sent to a central service that queries this master database. A query like `SELECT * FROM book_copies WHERE book_isbn = ? AND status = 'AVAILABLE'` will return a list of all available copies and their respective `branch_id`s. The UI can then display, "Available at Main Library, 2 copies available at North Campus Library."

### 2. Data Consistency for Concurrent Checkouts

**Problem:** If only one copy of a book remains in the entire system, how do you prevent two users at different branches from checking it out simultaneously?

**Solution:** This requires ensuring **atomicity** at the database level. The standard solution is to use **database transactions with pessimistic locking**.

1.  The `checkout_book` operation in the `BorrowingService` begins a database transaction.
2.  Before checking the book's availability, it reads the row for that specific `BookCopy` using a `SELECT ... FOR UPDATE` statement (in SQL databases). This places an **exclusive lock** on that row.
3.  The first user's transaction acquires the lock. It reads the status (`AVAILABLE`), proceeds to update the status to `LOANED`, and commits the transaction. The lock is then released.
4.  The second user's transaction, which was initiated at the same time, is **blocked** by the database, waiting to acquire the lock on that same row.
5.  Once the first transaction commits, the second transaction acquires the lock. It now re-reads the row, but this time the status is `LOANED`. The service then correctly informs the second user that the book is no longer available.

This approach guarantees **strong consistency** and prevents race conditions, which is critical for a system managing a finite inventory.

### 3. Scalability of the Central Database

**Problem:** As the number of branches, members, and transactions grows, the single central database can become a performance bottleneck.

**Solution:** **Sharding the database.** Sharding involves horizontally partitioning the data across multiple independent database servers.

1.  **Shard Key Selection:** The choice of a **shard key** is critical. A good shard key distributes the data and query load evenly.
    *   **Sharding by `branch_id`:** This is a natural starting point. All data for a specific library (its books, local members, loans) resides on one shard. This works well if branches are roughly the same size. However, a massive central library could still create a hotspot.
    *   **Sharding by `member_id`:** A more robust approach for user-centric data. A hash of the `member_id` is used to determine which shard stores that member's profile, loans, and reservations. This ensures an even distribution of write load as the number of users grows. The book catalog, which is read-heavy, might be replicated across all shards or live in its own service.

2.  **Application Layer:** The application's data access layer must be aware of the sharding scheme. It needs a routing mechanism to direct queries for a specific `member_id` to the correct database shard. This adds complexity but is a standard pattern for building large-scale systems.

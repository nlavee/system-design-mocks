# LLD Challenge: Design a Library Management System

## Problem Category: Complex System Logic & State Management

## Problem Description

Design the backend for a library management system. The system must track books, library members, and loans. It needs to enforce borrowing rules, manage reservations, and handle fines for overdue items.

### Core Requirements

1.  **Catalog Management:** The system must maintain a catalog of books. Each book has attributes like ISBN, title, author, and multiple copies can exist.
2.  **Member Management:** The system must manage user accounts. Different types of members (e.g., `Student`, `Faculty`) may have different borrowing privileges (e.g., loan duration, number of books allowed).
3.  **Core Operations:** The system must support:
    *   `checkout_book(member_id, book_copy_id)`: Loaning a book to a member.
    *   `return_book(book_copy_id)`: Returning a book.
    *   `reserve_book(member_id, book_title_id)`: Placing a reservation for a book that is currently unavailable.
4.  **Rule Enforcement:** The system must enforce rules such as borrowing limits and due dates. It should also calculate and apply fines for overdue books.

### LLD Focus & Evaluation Criteria

*   **Object-Oriented Modeling:** Your design should feature a clean and intuitive object model representing the core entities (`Book`, `BookCopy`, `Member`, `Loan`).
*   **Behavioral Patterns:** This problem is ideal for showcasing behavioral patterns:
    *   **Strategy Pattern:** Use this to implement different borrowing policies or fine calculation strategies for different member types (`StudentPolicy`, `FacultyPolicy`). This ensures the system is open to new policies.
    *   **Observer Pattern:** Use this to notify members when a book they have reserved becomes available.
*   **Data Integrity:** The system must ensure that the state of the library (e.g., who has which book) is always consistent.

### The System Design Edge: Concurrency & Distributed Systems

A Staff-level discussion must address the challenges of a large, multi-branch system. Be prepared to answer:

*   **Distributed Catalog:** How would your design change to support a university with multiple campus libraries? When a user searches for a book, the system needs to check availability across all branches in real-time.
*   **Data Consistency:** If there is only one copy of a rare book left in the entire multi-branch system, how do you prevent two users at different branches from checking it out simultaneously? This leads to a discussion of distributed transactions, locking, and consistency models (e.g., strong vs. eventual consistency).
*   **Scalability:** The central database managing loans and member information for all branches could become a bottleneck. How might you partition or shard the data (e.g., by member ID range, by home library branch) to ensure the system remains performant as it scales?

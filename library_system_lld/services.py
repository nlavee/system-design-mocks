from datetime import date
from models import Book, BookCopy, Member, Loan, BookStatus
from policies import BorrowingPolicy

# In a real application, these would be proper database-backed services.
# For this LLD, we use simple in-memory dictionaries to simulate a database.
class CatalogService:
    def __init__(self):
        self.books: dict[str, Book] = {}
        self.copies: dict[str, BookCopy] = {}

    def add_book_copy(self, book: Book, copy_id: str):
        if book.isbn not in self.books:
            self.books[book.isbn] = book
        copy = BookCopy(copy_id=copy_id, book=book)
        self.copies[copy_id] = copy

    def find_available_copy(self, isbn: str) -> BookCopy | None:
        for copy in self.copies.values():
            if copy.book.isbn == isbn and copy.status == BookStatus.AVAILABLE:
                return copy
        return None

class BorrowingService:
    """Main service class that orchestrates all operations."""
    def __init__(self, catalog_service: CatalogService, policy: BorrowingPolicy):
        self._catalog = catalog_service
        self._policy = policy
        self._loans: dict[str, Loan] = {}

    def checkout_book(self, member: Member, isbn: str) -> Loan | None:
        available_copy = self._catalog.find_available_copy(isbn)
        if not available_copy:
            print(f"Sorry {member.name}, no copies of ISBN {isbn} are available.")
            return None

        loan_duration = self._policy.get_loan_duration()
        checkout_date = date.today()
        due_date = checkout_date + loan_duration

        loan = Loan(member, available_copy, checkout_date, due_date)
        self._loans[available_copy.copy_id] = loan
        available_copy.status = BookStatus.LOANED

        print(f"Book '{available_copy.book.title}' checked out to {member.name}. Due: {due_date}")
        return loan

    def return_book(self, copy_id: str) -> None:
        if copy_id not in self._loans:
            print(f"Error: This book copy ({copy_id}) was not on loan.")
            return

        loan = self._loans.pop(copy_id)
        book_copy = loan.book_copy
        book_copy.status = BookStatus.AVAILABLE

        print(f"Book '{book_copy.book.title}' returned by {loan.member.name}.")

        # This is where the Observer pattern is triggered.
        book_copy.book.notify_observers()

    def reserve_book(self, member: Member, isbn: str) -> None:
        if isbn not in self._catalog.books:
            print("Error: Book not found in catalog.")
            return
        
        book = self._catalog.books[isbn]
        book.add_observer(member)
        print(f"Member {member.name} has reserved '{book.title}'. They will be notified upon availability.")

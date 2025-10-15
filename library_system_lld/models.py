from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import date

# Using forward declarations as strings for type hints to avoid circular imports
from typing import List, TYPE_CHECKING
if TYPE_CHECKING:
    from observers import Observer

class BookStatus(Enum):
    AVAILABLE = auto()
    LOANED = auto()
    RESERVED = auto()

@dataclass
class Book:
    """The abstract representation of a book (the Subject in the Observer pattern)."""
    isbn: str
    title: str
    author: str
    _observers: List[Observer] = field(default_factory=list, repr=False)

    def add_observer(self, observer: Observer) -> None:
        self._observers.append(observer)

    def remove_observer(self, observer: Observer) -> None:
        self._observers.remove(observer)

    def notify_observers(self) -> None:
        print(f"Notifying {len(self._observers)} observers for '{self.title}'...")
        for observer in self._observers:
            observer.update(self)

@dataclass
class BookCopy:
    """A specific physical copy of a book."""
    copy_id: str
    book: Book
    status: BookStatus = BookStatus.AVAILABLE

@dataclass
class Member:
    """A library member (the Observer in the Observer pattern)."""
    member_id: str
    name: str

    def update(self, book: Book) -> None:
        print(f"  - Notification for Member {self.name}: Book '{book.title}' is now available!")

@dataclass
class Loan:
    """Links a member to a book copy."""
    member: Member
    book_copy: BookCopy
    checkout_date: date
    due_date: date

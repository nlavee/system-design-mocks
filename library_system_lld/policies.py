from abc import ABC, abstractmethod
from datetime import date, timedelta

class BorrowingPolicy(ABC):
    """Interface for borrowing policies (the Strategy)."""
    @abstractmethod
    def get_loan_duration(self) -> timedelta:
        pass

    @abstractmethod
    def calculate_fine(self, days_overdue: int) -> float:
        pass

class StudentPolicy(BorrowingPolicy):
    """Concrete strategy for students."""
    def get_loan_duration(self) -> timedelta:
        return timedelta(days=14)

    def calculate_fine(self, days_overdue: int) -> float:
        return days_overdue * 0.25 # $0.25 per day

class FacultyPolicy(BorrowingPolicy):
    """Concrete strategy for faculty."""
    def get_loan_duration(self) -> timedelta:
        return timedelta(days=90)

    def calculate_fine(self, days_overdue: int) -> float:
        return days_overdue * 0.10 # $0.10 per day

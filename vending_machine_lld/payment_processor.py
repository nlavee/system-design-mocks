from abc import ABC, abstractmethod
from exceptions import InsufficientFundsException

class PaymentProcessor(ABC):
    """Interface for payment processing (Strategy Pattern)."""
    @abstractmethod
    def process_payment(self, price: float) -> float:
        """Processes the payment and returns the change. Raises exception on failure."""
        pass

    @abstractmethod
    def insert_money(self, amount: float) -> None:
        pass

    @abstractmethod
    def get_current_balance(self) -> float:
        pass

    @abstractmethod
    def cancel_transaction(self) -> float:
        """Cancels the transaction and returns the inserted money."""
        pass

class CashPaymentProcessor(PaymentProcessor):
    def __init__(self) -> None:
        self._balance = 0.0

    def insert_money(self, amount: float) -> None:
        if amount < 0:
            return
        self._balance += amount
        print(f"Inserted ${amount:.2f}. Current balance: ${self._balance:.2f}")

    def get_current_balance(self) -> float:
        return self._balance

    def process_payment(self, price: float) -> float:
        if self._balance < price:
            raise InsufficientFundsException(
                f"Insufficient funds. Required: ${price:.2f}, Balance: ${self._balance:.2f}"
            )
        
        change = self._balance - price
        self._balance = 0.0  # Reset balance after successful transaction
        print(f"Payment successful. Change: ${change:.2f}")
        return change

    def cancel_transaction(self) -> float:
        refund = self._balance
        self._balance = 0.0
        print(f"Transaction cancelled. Refunding ${refund:.2f}")
        return refund
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from exceptions import InvalidOperationException, ItemSoldOutException

# Use TYPE_CHECKING to avoid circular import issues at runtime
if TYPE_CHECKING:
    from vending_machine import VendingMachine

class State(ABC):
    """The interface for all State objects. It mirrors the actions a user can take."""
    def __init__(self, machine: VendingMachine):
        self._machine = machine

    def select_item(self, item_id: str) -> None:
        raise InvalidOperationException("Cannot select an item at this time.")

    def insert_money(self, amount: float) -> None:
        raise InvalidOperationException("Cannot insert money at this time.")

    def dispense_item(self) -> None:
        raise InvalidOperationException("Cannot dispense an item at this time.")

    def cancel(self) -> None:
        raise InvalidOperationException("Cannot cancel at this time.")


class IdleState(State):
    """The state when the machine is waiting for a user."""
    def select_item(self, item_id: str) -> None:
        inventory = self._machine.inventory_manager
        if not inventory.is_in_stock(item_id):
            self._machine.change_state(SoldOutState(self._machine))
            self._machine.state.select_item(item_id) # Delegate to the new state to display message
            return

        item = inventory.get_item(item_id)
        self._machine.selected_item = item
        print(f"Item '{item.name}' selected. Price: ${item.price:.2f}")
        self._machine.change_state(AcceptingMoneyState(self._machine))

    def cancel(self) -> None:
        print("Machine is idle. Nothing to cancel.")

class AcceptingMoneyState(State):
    """The state when an item has been selected and the machine is accepting money."""
    def insert_money(self, amount: float) -> None:
        self._machine.payment_processor.insert_money(amount)
        item = self._machine.selected_item
        balance = self._machine.payment_processor.get_current_balance()

        if balance >= item.price:
            self._machine.change_state(DispensingState(self._machine))
            self._machine.state.dispense_item()

    def cancel(self) -> None:
        self._machine.payment_processor.cancel_transaction()
        print("Transaction cancelled.")
        self._machine.change_state(IdleState(self._machine))

class DispensingState(State):
    """The state when the machine is dispensing an item and giving change."""
    def dispense_item(self) -> None:
        item = self._machine.selected_item
        try:
            self._machine.inventory_manager.dispense_item(item.item_id)
            self._machine.payment_processor.process_payment(item.price)
            print(f"Please take your item: {item.name}")
        except Exception as e:
            print(f"Error during dispensing: {e}. Refunding money.")
            self._machine.payment_processor.cancel_transaction()
        finally:
            self._machine.selected_item = None
            self._machine.change_state(IdleState(self._machine))

class SoldOutState(State):
    """A temporary state to inform the user an item is sold out."""
    def select_item(self, item_id: str) -> None:
        print(f"Sorry, item '{item_id}' is sold out.")
        self._machine.change_state(IdleState(self._machine))

    def cancel(self) -> None:
        print("Nothing to cancel.")
        self._machine.change_state(IdleState(self._machine))
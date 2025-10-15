from inventory_manager import InventoryManager
from payment_processor import PaymentProcessor, CashPaymentProcessor
from models import Item
from states import State, IdleState
from typing import List, Optional

class VendingMachine:
    """The Context class. It holds the current state and delegates all actions to it."""
    def __init__(self, inventory: List[Item], payment_processor: PaymentProcessor):
        self.inventory_manager = InventoryManager(inventory)
        self.payment_processor = payment_processor
        self.state: State = IdleState(self)
        self.selected_item: Optional[Item] = None
        print("Vending Machine is now in Idle State.")

    def change_state(self, new_state: State) -> None:
        print(f"Changing state from {self.state.__class__.__name__} to {new_state.__class__.__name__}")
        self.state = new_state

    # User actions are delegated to the current state object
    def select_item(self, item_id: str) -> None:
        try:
            self.state.select_item(item_id)
        except Exception as e:
            print(f"Error: {e}")

    def insert_money(self, amount: float) -> None:
        try:
            self.state.insert_money(amount)
        except Exception as e:
            print(f"Error: {e}")

    def cancel(self) -> None:
        try:
            self.state.cancel()
        except Exception as e:
            print(f"Error: {e}")

# Example of how to run the machine
if __name__ == '__main__':
    # 1. Setup initial inventory
    initial_inventory = [
        Item(item_id="101", name="Cola", price=1.50, quantity=5),
        Item(item_id="102", name="Chips", price=1.00, quantity=10),
        Item(item_id="103", name="Candy", price=0.75, quantity=1),
    ]

    # 2. Initialize the Vending Machine with components
    cash_processor = CashPaymentProcessor()
    machine = VendingMachine(inventory=initial_inventory, payment_processor=cash_processor)

    print("\n--- Scenario 1: Successful Purchase ---")
    machine.select_item("101")      # Select Cola
    machine.insert_money(1.00)
    machine.insert_money(0.50)

    print("\n--- Scenario 2: Insufficient Funds & Cancel ---")
    machine.select_item("102")      # Select Chips
    machine.insert_money(0.50)
    machine.cancel()                # User cancels

    print("\n--- Scenario 3: Item Sold Out ---")
    machine.select_item("103")      # Select Candy
    machine.insert_money(1.00)      # Buy the last one
    machine.select_item("103")      # Try to select again

    print("\n--- Scenario 4: Invalid Operation ---")
    machine.insert_money(1.00)      # Try to insert money while idle
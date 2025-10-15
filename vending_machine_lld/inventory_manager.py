from models import Item
from exceptions import ItemNotFoundException
from typing import List, Dict

class InventoryManager:
    """Manages the item inventory. Adheres to SRP."""
    def __init__(self, inventory: List[Item]):
        # Store the full Item object for better type safety and less brittle code
        self._inventory: Dict[str, Item] = {item.item_id: item for item in inventory}

    def get_item(self, item_id: str) -> Item:
        if item_id not in self._inventory:
            raise ItemNotFoundException(f"Item with ID '{item_id}' not found.")
        return self._inventory[item_id]

    def is_in_stock(self, item_id: str) -> bool:
        item = self.get_item(item_id)
        return item.quantity > 0

    def dispense_item(self, item_id: str) -> None:
        """Reduces stock by one for the given item."""
        if not self.is_in_stock(item_id):
            # This should ideally not be reached if logic is correct, but serves as a safeguard
            raise ItemNotFoundException(f"Cannot dispense sold out item '{item_id}'.")
        
        item = self._inventory[item_id]
        self._inventory[item_id] = Item(
            item_id=item.item_id,
            name=item.name,
            price=item.price,
            quantity=item.quantity - 1
        )
        print(f"Dispensed one '{item.name}'. Remaining stock: {self._inventory[item_id].quantity}")
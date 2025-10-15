from dataclasses import dataclass

@dataclass(frozen=True)
class Item:
    """Immutable model for an item in the inventory."""
    item_id: str
    name: str
    price: float
    quantity: int
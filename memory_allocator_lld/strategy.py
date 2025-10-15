from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from allocator import _Block

class AllocationStrategy(ABC):
    """Interface for different memory allocation strategies."""

    @abstractmethod
    def find(self, size: int, free_list_head: Optional[_Block]) -> Optional[_Block]:
        """Finds a suitable free block from the free list."""
        pass


class FirstFitStrategy(AllocationStrategy):
    """Scans the free list and chooses the first block that is large enough."""

    def find(self, size: int, free_list_head: Optional[_Block]) -> Optional[_Block]:
        current_block = free_list_head
        while current_block:
            if current_block.size >= size:
                return current_block
            current_block = current_block.next_free
        return None


class BestFitStrategy(AllocationStrategy):
    """Scans the entire free list to find the smallest block that is large enough."""

    def find(self, size: int, free_list_head: Optional[_Block]) -> Optional[_Block]:
        best_block: Optional[_Block] = None
        current_block = free_list_head
        while current_block:
            if current_block.size >= size:
                if best_block is None or current_block.size < best_block.size:
                    best_block = current_block
            current_block = current_block.next_free
        return best_block

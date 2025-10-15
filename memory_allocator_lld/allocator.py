from __future__ import annotations
import struct
from typing import Optional

from strategy import AllocationStrategy, FirstFitStrategy
from exceptions import OutOfMemoryException, InvalidPointerException

# struct format for the block header: size (unsigned long long), is_free (bool)
HEADER_FORMAT = "<Q?"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# struct format for the free list pointers: next_ptr (Q), prev_ptr (Q)
POINTER_FORMAT = "<QQ"
POINTER_SIZE = struct.calcsize(POINTER_FORMAT)

MIN_BLOCK_SIZE = HEADER_SIZE + POINTER_SIZE


class _Block:
    """A private helper class to provide an object-oriented view over a memory block."""

    def __init__(self, memory: bytearray, ptr: int):
        self.memory = memory
        self.ptr = ptr  # Pointer to the start of the block (and its header)

    @property
    def header(self) -> tuple[int, bool]:
        return struct.unpack_from(HEADER_FORMAT, self.memory, self.ptr)

    @property
    def size(self) -> int:
        return self.header[0]

    @size.setter
    def size(self, value: int):
        is_free = self.is_free
        struct.pack_into(HEADER_FORMAT, self.memory, self.ptr, value, is_free)

    @property
    def is_free(self) -> bool:
        return self.header[1]

    @is_free.setter
    def is_free(self, value: bool):
        size = self.size
        struct.pack_into(HEADER_FORMAT, self.memory, self.ptr, size, value)

    @property
    def data_ptr(self) -> int:
        return self.ptr + HEADER_SIZE

    def _get_free_pointers(self) -> tuple[int, int]:
        return struct.unpack_from(POINTER_FORMAT, self.memory, self.data_ptr)

    @property
    def next_free_ptr(self) -> int:
        return self._get_free_pointers()[0]

    @property
    def prev_free_ptr(self) -> int:
        return self._get_free_pointers()[1]

    @property
    def next_free(self) -> Optional[_Block]:
        ptr = self.next_free_ptr
        return _Block(self.memory, ptr) if ptr != 0 else None

    @property
    def prev_free(self) -> Optional[_Block]:
        ptr = self.prev_free_ptr
        return _Block(self.memory, ptr) if ptr != 0 else None

    def set_free_pointers(self, next_ptr: int, prev_ptr: int):
        struct.pack_into(POINTER_FORMAT, self.memory,
                         self.data_ptr, next_ptr, prev_ptr)


class MemoryAllocator:
    def __init__(self, total_size: int, strategy: AllocationStrategy = FirstFitStrategy()):
        if total_size < MIN_BLOCK_SIZE:
            raise ValueError(f"Total size must be at least {MIN_BLOCK_SIZE}")
        self.memory = bytearray(total_size)
        self.strategy = strategy
        self.free_list_head: Optional[_Block] = _Block(self.memory, 0)
        self.free_list_head.size = total_size
        self.free_list_head.is_free = True
        self.free_list_head.set_free_pointers(0, 0)  # next=0, prev=0 (null)

    def allocate(self, size: int) -> int:
        if size <= 0:
            raise ValueError("Allocation size must be positive.")

        required_size = size + HEADER_SIZE
        best_block = self.strategy.find(required_size, self.free_list_head)

        if not best_block:
            raise OutOfMemoryException(f"Cannot allocate {size} bytes.")

        # If the block is large enough, split it
        if best_block.size >= required_size + MIN_BLOCK_SIZE:
            new_block_ptr = best_block.ptr + required_size
            new_block = _Block(self.memory, new_block_ptr)
            new_block.size = best_block.size - required_size
            new_block.is_free = True
            self._add_to_free_list(new_block)

            best_block.size = required_size

        # Mark the block as allocated and remove from free list
        best_block.is_free = False
        self._remove_from_free_list(best_block)

        return best_block.data_ptr

    def free(self, ptr: int):
        if ptr < HEADER_SIZE:
            raise InvalidPointerException("Invalid pointer provided.")

        block_ptr = ptr - HEADER_SIZE
        block_to_free = _Block(self.memory, block_ptr)

        if block_to_free.is_free:
            raise InvalidPointerException("Double free detected.")

        block_to_free.is_free = True

        # Coalesce with next physical block
        next_physical_block_ptr = block_to_free.ptr + block_to_free.size
        if next_physical_block_ptr < len(self.memory):
            next_block = _Block(self.memory, next_physical_block_ptr)
            if next_block.is_free:
                self._remove_from_free_list(next_block)
                block_to_free.size += next_block.size

        # Coalesce with previous physical block (more complex)
        # This simplified version only adds the current block back.
        # A full implementation would need to find the previous physical block.
        self._add_to_free_list(block_to_free)

    def _add_to_free_list(self, block: _Block):
        # Add to the head of the list
        next_head = self.free_list_head
        if next_head:
            block.set_free_pointers(next_head.ptr, 0)
            next_head.set_free_pointers(next_head.next_free_ptr, block.ptr)
        else:
            block.set_free_pointers(0, 0)
        self.free_list_head = block

    def _remove_from_free_list(self, block: _Block):
        prev_block, next_block = block.prev_free, block.next_free

        if prev_block:
            prev_block.set_free_pointers(
                block.next_free_ptr, prev_block.prev_free_ptr)
        else:  # It was the head
            self.free_list_head = next_block

        if next_block:
            next_block.set_free_pointers(
                next_block.next_free_ptr, block.prev_free_ptr)

class MemoryAllocatorException(Exception):
    """Base class for allocator-specific errors."""
    pass

class OutOfMemoryException(MemoryAllocatorException):
    """Raised when an allocation request cannot be satisfied."""
    pass

class InvalidPointerException(MemoryAllocatorException):
    """Raised when a pointer passed to free() is invalid."""
    pass

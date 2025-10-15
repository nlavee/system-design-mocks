class VendingMachineException(Exception):
    """Base exception for all vending machine errors."""
    pass

class ItemNotFoundException(VendingMachineException):
    pass

class ItemSoldOutException(VendingMachineException):
    pass

class InsufficientFundsException(VendingMachineException):
    pass

class InvalidOperationException(VendingMachineException):
    pass

from dataclasses import dataclass

@dataclass(frozen=True)
class Operand:
    """Immutable value object for an operand, separating sign from absolute value."""
    absolute_value: int
    is_negative: bool

    @classmethod
    def from_integer(cls, value: int) -> 'Operand':
        if not isinstance(value, int):
            raise TypeError("Operand value must be an integer.")
        return cls(abs(value), value < 0)

@dataclass(frozen=True)
class DivisionResult:
    """Immutable value object for the result of a division."""
    quotient: int
    remainder: int

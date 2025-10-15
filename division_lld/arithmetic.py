from models import Operand, DivisionResult
from instructions import InstructionSet
from exceptions import DivisionByZeroException

class ArithmeticUnit:
    """Orchestrates the division process using a specified instruction set.
    This class adheres to DIP, depending on the InstructionSet abstraction.
    """
    def __init__(self, instruction_set: InstructionSet):
        self._instruction_set = instruction_set

    def divide(self, dividend: Operand, divisor: Operand) -> DivisionResult:
        """Performs robust division, handling validation and sign logic."""
        # 1. Validation (Robustness)
        if divisor.absolute_value == 0:
            raise DivisionByZeroException("Divisor cannot be zero.")

        # 2. Delegate core calculation to the injected strategy (DIP/OCP)
        quotient_abs, remainder_abs = self._instruction_set.divide(
            dividend.absolute_value, 
            divisor.absolute_value
        )

        # 3. Handle sign logic
        quotient_is_negative = dividend.is_negative != divisor.is_negative
        
        final_quotient = -quotient_abs if quotient_is_negative else quotient_abs
        final_remainder = -remainder_abs if dividend.is_negative else remainder_abs

        return DivisionResult(quotient=final_quotient, remainder=final_remainder)

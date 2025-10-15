from abc import ABC, abstractmethod

class InstructionSet(ABC):
    """Interface (Strategy) for low-level arithmetic operations."""
    @abstractmethod
    def divide(self, dividend_abs: int, divisor_abs: int) -> tuple[int, int]:
        """Performs division on absolute values, returning (quotient, remainder)."""
        pass

class BitwiseInstructionSet(InstructionSet):
    """Implements division using efficient bitwise shifts and subtraction."""
    def divide(self, dividend_abs: int, divisor_abs: int) -> tuple[int, int]:
        if divisor_abs > dividend_abs:
            return 0, dividend_abs

        quotient = 0
        temp_divisor = divisor_abs
        
        # Find the largest power of 2 that the divisor can be multiplied by
        # without exceeding the dividend.
        power = 0
        while (temp_divisor << 1) <= dividend_abs:
            temp_divisor <<= 1
            power += 1

        # Repeatedly subtract these scaled divisors
        while power >= 0:
            if dividend_abs >= temp_divisor:
                dividend_abs -= temp_divisor
                quotient += 1 << power
            
            temp_divisor >>= 1
            power -= 1
            
        return quotient, dividend_abs

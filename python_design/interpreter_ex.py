import sys
import argparse

# --- Exercise 2: Better Error Handling ---
# Reasoning: Using a custom exception class allows us to distinguish between
# errors in the user's program and actual bugs in the interpreter itself.
class TLLException(Exception):
    pass

def check(condition, message):
    """Reasoning: Centralizing checks makes it easier to change error behavior later."""
    if not condition:
        raise TLLException(message)

# --- Core Interpreter Implementation ---

class Interpreter:
    def __init__(self, trace=False):
        self.trace = trace
        # Dynamic dispatch table: maps operation names to handler functions.
        # Reasoning: Using a table is more efficient and cleaner than a long if/elif chain.
        self.OPS = {
            "add": self.do_add,
            "sub": self.do_sub,
            "mul": self.do_mul,
            "div": self.do_div,
            "leq": self.do_leq,
            "if": self.do_if,
            "set": self.do_set,
            "get": self.do_get,
            "seq": self.do_seq,
            # Exercise 1: Arrays
            "array": self.do_array,
            "aget": self.do_aget,
            "aset": self.do_aset,
            # Exercise 3: More Statements
            "print": self.do_print,
            "repeat": self.do_repeat,
            # Exercise 5: While Loops
            "while": self.do_while,
            # Exercise 2: Catch statement
            "catch": self.do_catch,
        }

    def do(self, env, expr):
        """
        Main evaluation function.
        Reasoning: Recursively evaluates expressions based on their type.
        """
        if isinstance(expr, (int, float)):
            return expr
        
        if isinstance(expr, str):
            # If it's a known variable, return its value.
            # Otherwise, treat it as a string literal.
            # Reasoning: This allows using "n" as a shorthand for ["get", "n"]
            # while still allowing literal messages in print statements.
            return env.get(expr, expr)

        check(isinstance(expr, list), f"Expected list or int, got {type(expr)}")
        check(len(expr) > 0, "Empty expression list")

        op_name = expr[0]
        args = expr[1:]
        
        check(op_name in self.OPS, f"Unknown operation: {op_name}")
        handler = self.OPS[op_name]

        # Exercise 4: Tracing
        if self.trace:
            print(f"TRACE: Calling {op_name} with {args}")

        result = handler(env, args)

        if self.trace:
            print(f"TRACE: {op_name} returned {result}")
            
        return result

    # --- Operation Handlers ---

    def do_add(self, env, args):
        check(len(args) == 2, "add expects 2 arguments")
        return self.do(env, args[0]) + self.do(env, args[1])

    def do_sub(self, env, args):
        check(len(args) == 2, "sub expects 2 arguments")
        return self.do(env, args[0]) - self.do(env, args[1])
    
    def do_mul(self, env, args):
        check(len(args) == 2, "mul expects 2 arguments")
        return self.do(env, args[0]) * self.do(env, args[1])

    def do_div(self, env, args):
        check(len(args) == 2, "div expects 2 arguments")
        divisor = self.do(env, args[1])
        check(divisor != 0, "Division by zero")
        return self.do(env, args[0]) // divisor

    def do_leq(self, env, args):
        check(len(args) == 2, "leq expects 2 arguments")
        return 1 if self.do(env, args[0]) <= self.do(env, args[1]) else 0

    def do_if(self, env, args):
        check(len(args) == 3, "if expects condition, then-branch, and else-branch")
        condition = self.do(env, args[0])
        if condition != 0:
            return self.do(env, args[1])
        else:
            return self.do(env, args[2])

    def do_set(self, env, args):
        check(len(args) == 2, "set expects variable name and value")
        name = args[0]
        value = self.do(env, args[1])
        env[name] = value
        return value

    def do_get(self, env, args):
        check(len(args) == 1, "get expects variable name")
        name = args[0]
        check(name in env, f"Undefined variable: {name}")
        return env[name]

    def do_seq(self, env, args):
        """Reasoning: Executes a list of expressions and returns the result of the last one."""
        result = None
        for expr in args:
            result = self.do(env, expr)
        return result

    # --- Exercise 1: Arrays ---
    # Reasoning: Arrays are stored as Python lists in the environment.
    def do_array(self, env, args):
        check(len(args) == 1, "array expects size")
        size = self.do(env, args[0])
        check(size >= 0, "Array size must be non-negative")
        return [0] * size

    def do_aget(self, env, args):
        check(len(args) == 2, "aget expects array and index")
        arr = self.do(env, args[0])
        index = self.do(env, args[1])
        check(isinstance(arr, list), "aget target must be an array")
        check(0 <= index < len(arr), f"Array index out of bounds: {index}")
        return arr[index]

    def do_aset(self, env, args):
        check(len(args) == 3, "aset expects array, index, and value")
        arr = self.do(env, args[0])
        index = self.do(env, args[1])
        value = self.do(env, args[2])
        check(isinstance(arr, list), "aset target must be an array")
        check(0 <= index < len(arr), f"Array index out of bounds: {index}")
        arr[index] = value
        return value

    # --- Exercise 3: More Statements ---
    def do_print(self, env, args):
        """Reasoning: Evaluates and prints each argument, followed by a newline."""
        values = [str(self.do(env, arg)) for arg in args]
        print(" ".join(values))
        return 0

    def do_repeat(self, env, args):
        """
        Reasoning: repeat(n, body) executes body n times. 
        Handles n=0 by not executing the body and returning 0.
        """
        check(len(args) == 2, "repeat expects count and body")
        count = self.do(env, args[0])
        result = 0
        for _ in range(count):
            result = self.do(env, args[1])
        return result

    # --- Exercise 5: While Loops ---
    def do_while(self, env, args):
        """Reasoning: Continually evaluates condition and executes body while condition is non-zero."""
        check(len(args) == 2, "while expects condition and body")
        result = 0
        while self.do(env, args[0]) != 0:
            result = self.do(env, args[1])
        return result

    # --- Exercise 2: Catch Statement ---
    def do_catch(self, env, args):
        """
        Reasoning: catch(try_expr, handle_expr) executes try_expr. 
        If it raises TLLException, it executes handle_expr.
        """
        check(len(args) == 2, "catch expects try_expression and handler_expression")
        try:
            return self.do(env, args[0])
        except TLLException:
            return self.do(env, args[1])

# --- Main Runner ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TLL Interpreter")
    parser.add_argument("--trace", action="store_true", help="Enable execution tracing")
    args = parser.parse_args()

    interp = Interpreter(trace=args.trace)
    env = {}

    print("--- Running Demo Program ---")
    # A program that calculates 10! using repeat
    prog_factorial = [
        "seq",
        ["set", "n", 10],
        ["set", "res", 1],
        ["repeat", "n", [
            "seq",
            ["set", "res", ["mul", "res", "n"]],
            ["set", "n", ["sub", "n", 1]]
        ]],
        ["print", "Factorial result:", "res"]
    ]
    interp.do(env, prog_factorial)

    print("\n--- Running Array Demo ---")
    # Create an array, fill it with squares, and print it
    prog_array = [
        "seq",
        ["set", "my_arr", ["array", 5]],
        ["set", "i", 0],
        ["while", ["leq", "i", 4], [
            "seq",
            ["aset", "my_arr", "i", ["mul", "i", "i"]],
            ["set", "i", ["add", "i", 1]]
        ]],
        ["print", "Array values:", ["aget", "my_arr", 0], ["aget", "my_arr", 1], ["aget", "my_arr", 2]]
    ]
    interp.do(env, prog_array)

    print("\n--- Running Error Handling Demo ---")
    # Attempt division by zero and catch it
    prog_error = [
        "seq",
        ["print", "Attempting 1/0 inside catch..."],
        ["set", "err_res", ["catch", ["div", 1, 0], 999]],
        ["print", "Result after catch:", "err_res"]
    ]
    interp.do(env, prog_error)

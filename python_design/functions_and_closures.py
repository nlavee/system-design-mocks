# functions_and_closures.py

"""
This file implements the core components for handling functions and their calls
within a simple mini-language interpreter, based on Chapter 8: Functions and Closures
from "Software Design by Example" (https://third-bit.com/sdxpy/func/).

This version includes a comprehensive set of solutions to the exercises presented
in the chapter, demonstrating a deeper exploration of the concepts.
"""


# --- Environment Management ---
def env_get(env_stack: list[dict], name: str):
    for frame in reversed(env_stack):
        if name in frame:
            return frame[name]
    raise NameError(f"Name '{name}' not found in environment.")


def env_set(env_stack: list[dict], name: str, value):
    env_stack[-1][name] = value


# --- Function Definition and Call Handlers ---
def _do_func_handler(env_stack: list[dict], args: list):
    assert len(args) == 2, "func expects 2 arguments: [params_list, body_expr]"
    return ["func", args[0], args[1]]


def _do_call_handler(env_stack: list[dict], args: list):
    """
    Handles the "call" operation.
    (Exercise Solution for loop-based frame creation is implemented here).
    """
    assert len(args) >= 1, "call expects at least 1 argument"
    name = args[0]
    values = [do(env_stack, a) for a in args[1:]]
    func = env_get(env_stack, name)

    assert isinstance(func, list) and (
        func[0] == "func"
    ), f"'{name}' is not a function."
    params, body = func[1], func[2]

    # (Exercise Solution for Arity Mismatch)
    # The following line checks if the number of arguments matches the number of parameters.
    assert len(values) == len(
        params
    ), f"Function '{name}' expected {len(params)} arguments, but got {len(values)}."

    # (Exercise Solution for loop-based frame)
    new_frame = {}
    for i in range(len(params)):
        new_frame[params[i]] = values[i]
    env_stack.append(new_frame)

    result = do(env_stack, body)
    env_stack.pop()
    return result


# --- Main Interpreter Loop (Dynamic Scoping) ---
def do(env_stack: list[dict], expr):
    if not isinstance(expr, list):
        return expr
    op, *args = expr
    if op == "func":
        return _do_func_handler(env_stack, args)
    if op == "call":
        return _do_call_handler(env_stack, args)
    if op == "set":
        env_set(env_stack, args[0], do(env_stack, args[1]))
        return None
    if op == "get":
        return env_get(env_stack, args[0])
    if op == "add":
        return do(env_stack, args[0]) + do(env_stack, args[1])
    if op == "print":
        print(do(env_stack, args[0]))
        return None
    if op == "seq":
        result = None
        for sub_expr in args:
            result = do(env_stack, sub_expr)
        return result
    if op == "repeat":
        count = do(env_stack, args[0])
        result = None
        for _ in range(count):
            result = do(env_stack, args[1])
        return result
    raise ValueError(f"Unknown operation: {op}")


# --- Base Example Program ---
example_program = [
    "seq",
    ["set", "double", ["func", ["num"], ["add", ["get", "num"], ["get", "num"]]]],
    ["set", "a", 1],
    [
        "repeat",
        4,
        [
            "seq",
            ["set", "a", ["call", "double", ["get", "a"]]],
            ["print", ["get", "a"]],
        ],
    ],
]

# --- EXERCISE SOLUTIONS ---


# This section provides solutions and detailed explanations for the exercises

# presented in Chapter 8: Functions and Closures of "Software Design by Example".


# --- Exercise: Working Counter ---

# This exercise explores different ways to implement a counter function in Python

# that "remembers" its state across calls, specifically addressing Python's

# variable binding rules in closures.


def make_counter_mutable():
    """

    (Solution using a mutable object).

    This implementation uses a mutable list to hold the counter's state.

    The inner function `_inner` closes over the `value` list. When `_inner`

    modifies `value[0]`, it's modifying the *contents* of the list object

    that it has a reference to, not reassigning the `value` variable itself.

    This bypasses Python's default behavior where assignment to a variable

    within an inner scope creates a new local variable unless `nonlocal` is used.

    """

    value = [0]  # `value` is a list (mutable object)

    def _inner():

        # Modifies the element of the captured list, not the list variable itself.

        value[0] += 1

        return value[0]

    return _inner


def make_counter_nonlocal():
    """

    (Solution using the `nonlocal` keyword).

    This is the modern and Pythonic way to implement a counter closure.

    The `nonlocal` keyword explicitly tells Python that `value` refers to the

    variable in the nearest enclosing scope (i.e., `make_counter_nonlocal`'s scope)

    that is not global. This allows the inner function to directly modify

    the `value` variable from its enclosing scope.

    """

    value = 0  # `value` is an integer (immutable object)

    def _inner():

        nonlocal value  # Declare that `value` is not local to `_inner`

        value += 1  # Now modifies the `value` from the outer scope

        return value

    return _inner


# --- Exercise: Chained Maps for Lexical Scoping ---


# This exercise demonstrates how to implement lexical scoping in our mini-interpreter
# using "chained maps" (a linked list of environments). Lexical scoping means
# that variables are resolved based on where the function was *defined*
# (the structure of the code), not where it is *called*.
class ChainedMap:
    """
    Represents a single scope (or stack frame) in a lexically-scoped environment.
    Each ChainedMap holds its local variables and a reference to its parent scope.
    """

    def __init__(self, parent=None):
        """
        Initializes a new scope. The `parent` argument establishes the chain.
        """
        self.frame = {}  # Dictionary for local variables in this scope
        self.parent = parent  # Reference to the enclosing (parent) scope

    def get(self, name: str):
        """
        Retrieves a variable's value by searching up the chain of scopes.
        This implements lexical lookup: it first checks the current frame,
        then its parent, and so on, until the global scope.
        """
        if name in self.frame:
            return self.frame[name]
        if self.parent:
            return self.parent.get(name)  # Recursively search parent scope

        raise NameError(f"Name '{name}' not found")

    def set(self, name: str, value):
        """
        Sets a variable's value in the current, most specific scope.
        In this simple model, assignment always happens in the current frame.
        """
        self.frame[name] = value


def do_lexical(env: ChainedMap, expr):
    """
    An interpreter function designed to work with `ChainedMap` environments,
    thereby enforcing lexical scoping.
    Key differences from `do` (dynamic scoping):
    - Environment (`env`) is a `ChainedMap` instance, not a list.
    - Function definitions (`func`) capture their definition-time environment (`env`)
      to form a "closure" (stored as `["closure", ..., def_env]`).
    - Function calls (`call`) create a new `ChainedMap` whose parent is the
      `def_env` of the captured closure, correctly preserving lexical context.
    """
    if not isinstance(expr, list):
        # Handle bare identifiers (strings) as variable lookups.
        if isinstance(expr, str) and expr.isidentifier():
            try:
                return env.get(expr)  # Lexical lookup for variables
            except NameError:
                return expr  # If not a variable, treat as a literal string
        return expr  # Literal values (numbers, non-identifier strings)
    op, *args = expr

    if op == "set":
        # Evaluate the value and set it in the current lexical scope.
        env.set(args[0], do_lexical(env, args[1]))
        return None
    elif op == "func":
        # When a function is *defined*, we capture the current lexical environment (`env`).
        # This captured environment (`def_env`) will be used later when the function is *called*,
        # allowing it to access variables from its definition context (closure).
        return [
            "closure",
            args[0],
            args[1],
            env,
        ]  # ["closure", params, body, definition_env]
    elif op == "call":
        func_expr = args[0]
        # Evaluate the function expression to get the closure data.
        closure = do_lexical(env, func_expr)
        # we need to retrieve the closure from the environment.
        if isinstance(closure, str) and closure.isidentifier():
            closure = env.get(closure)
        closure_type, params, body, def_env = closure
        assert (
            closure_type == "closure"
        ), f"'{func_expr}' is not a callable function (closure)."
        # Evaluate arguments in the *calling* environment.
        arg_values = [do_lexical(env, arg) for arg in args[1:]]

        # Create a new environment for the function's execution.
        # CRUCIALLY, the parent of this new environment is the `def_env` (the environment
        # where the function was defined), *not* the calling environment. This enforces lexical scoping.
        call_env = ChainedMap(parent=def_env)

        # Assign argument values to parameters in the new call environment.
        assert len(params) == len(
            arg_values
        ), f"Function arity mismatch for {func_expr}"
        for i in range(len(params)):
            call_env.set(params[i], arg_values[i])

        # Execute the function's body within its new, lexically-scoped environment.
        return do_lexical(call_env, body)
    elif op == "add":
        return do_lexical(env, args[0]) + do_lexical(env, args[1])
    elif op == "seq":
        result = None
        for sub_expr in args:
            result = do_lexical(env, sub_expr)
        return result
    raise ValueError(f"Unknown operation: {op}")


# --- Exercise: Implicit Sequence ---
# This exercise demonstrates how to make the mini-language more ergonomic
# by implicitly treating a list of expressions as a sequence if it's not
# an explicit operation (like "set", "call", etc.). This avoids the need
# to always wrap multiple expressions in a `["seq", ...]` form.
def do_implicit(env_stack: list, expr):
    """
    An interpreter that handles implicit sequences in a dynamic-scoped context.
    This `do_implicit` interpreter is a self-contained version for demonstration,
    it includes its own `env_get_implicit` and `env_set_implicit` helpers.
    """

    # Helper functions for environment access, locally defined for this interpreter.
    def env_get_implicit(name):
        for frame in reversed(env_stack):
            if name in frame:
                return frame[name]
        raise NameError(f"Name '{name}' not found")

    def env_set_implicit(name, value):
        env_stack[-1][name] = value

    # Base case: if not a list, it's a literal or potentially a variable.
    if not isinstance(expr, list):
        # If it's a string identifier, attempt to retrieve its value from the environment.
        if isinstance(expr, str) and expr.isidentifier():
            try:
                return env_get_implicit(expr)
            except NameError:
                return expr  # If not found, treat as a literal string.
        return expr  # Return literal numbers or non-identifier strings.

    # Implicit Sequence Detection:
    # If the expression is a list, and its first element is also a list,
    # we assume it's an implicit sequence of expressions to be executed.
    # E.g., `[[set, x, 1], [add, x, 2]]` vs `[set, x, 1]`.
    if len(expr) > 0 and isinstance(expr[0], list):
        result = None
        for sub_expr in expr:
            # Recursively call do_implicit for each sub-expression in the sequence.
            result = do_implicit(env_stack, sub_expr)
        return (
            result  # The result of the sequence is the result of its last expression.
        )

    # If it's an explicit operation (e.g., ["set", ...], ["call", ...])
    op, *args = expr
    if op == "set":
        # Evaluate the value and set it in the current dynamic scope.
        env_set_implicit(args[0], do_implicit(env_stack, args[1]))
        return None
    elif op == "get":
        return env_get_implicit(args[0])
    elif op == "add":
        return do_implicit(env_stack, args[0]) + do_implicit(env_stack, args[1])

    elif op == "func":
        # Function definition, stores params and body.
        return ["func", args[0], args[1]]
    elif op == "call":
        # Function call logic.
        func = env_get_implicit(args[0])
        params, body = func[1], func[2]
        values = [do_implicit(env_stack, a) for a in args[1:]]
        # Create a new stack frame for the function's local variables.
        new_frame = dict(zip(params, values))
        env_stack.append(new_frame)

        # Execute the function's body. The body itself might be an implicit sequence,
        # which the recursive call to `do_implicit` will handle.
        result = do_implicit(env_stack, body)
        env_stack.pop()  # Remove the stack frame after function execution.
        return result
    elif op == "seq":
        # Explicit sequence operator, behaves the same as implicit sequence.
        result = None
        for sub_expr in args:
            result = do_implicit(env_stack, sub_expr)
        return result
    raise ValueError(f"Unknown operation: {op}")


# --- Main Execution Block ---

if __name__ == "__main__":

    print("--- Running Base Example Program (Dynamic Scoping) ---")

    # This demonstrates the original interpreter with dynamic scoping.

    # Expected output: 2, 4, 8, 16

    do([{}], example_program)

    print("--- Base Program Finished ---\n")

    print("--- EXERCISE DEMONSTRATIONS ---\n")

    # 1. Arity Mismatch

    print("1. Arity Mismatch Test:")

    # This program defines a function `add` expecting two arguments,

    # but then calls it with only one. The `assert` in `_do_call_handler`

    # (which is part of the original interpreter) should catch this.

    arity_mismatch_program = [
        "seq",
        ["set", "add", ["func", ["a", "b"], ["add", ["get", "a"], ["get", "b"]]]],
        [
            "call",
            "add",
            5,
        ],  # Calling with 1 arg instead of 2, will cause an AssertionError
    ]

    try:

        do([{}], arity_mismatch_program)

    except AssertionError as e:

        print(f"  Successfully caught arity mismatch error: {e}\n")

    else:

        print("  Error: Arity mismatch not caught.\n")

    # 2. Loop-based Stack Frame Creation

    print("2. Loop-based Stack Frame Creation Test:")

    print(
        "  The `_do_call_handler` function already includes the solution for this exercise."
    )

    print("  Instead of `dict(zip(params, values))`, it uses a `for` loop to manually")

    print(
        "  construct the new function call frame, demonstrating direct variable binding.\n"
    )

    # 3. Working Counter Test

    print("3. Working Counter Test (Closure Behavior):")

    # Demonstrates the two common Pythonic ways to create a counter closure

    # that correctly modifies state.

    print("  Mutable list counter:")

    counter_m = make_counter_mutable()

    print(f"    Call 1: {counter_m()}")  # Expected: 1

    print(f"    Call 2: {counter_m()}")  # Expected: 2

    print(f"    Call 3: {counter_m()}\n")  # Expected: 3

    print("  `nonlocal` keyword counter:")

    counter_nl = make_counter_nonlocal()

    print(f"    Call 1: {counter_nl()}")  # Expected: 1

    print(f"    Call 2: {counter_nl()}")  # Expected: 2

    print(f"    Call 3: {counter_nl()}\n")  # Expected: 3

    # 4. Chained Maps for Lexical Scoping

    print("4. Lexical Scoping with Chained Maps Test:")

    # This example demonstrates a core concept of lexical scoping:

    # a function "remembers" the environment in which it was *defined*.

    # The `make_adder` function defines an inner function that closes over `n`.

    # When `add_five` is called later, it still has access to the `n=5` from

    # its definition context, even though `make_adder` has already returned.

    lexical_program = [
        "seq",
        [
            "set",
            "make_adder",  # Define a function that returns another function (a closure)
            [
                "func",
                ["n"],  # Outer function `make_adder` takes `n`
                ["func", ["x"], ["add", "x", "n"]],  # Inner function closes over `n`
            ],
        ],
        [
            "set",
            "add_five",
            ["call", "make_adder", 5],
        ],  # `add_five` is now a closure where `n` is 5
        [
            "set",
            "result",
            ["call", "add_five", 10],
        ],  # Call `add_five` with `x=10`. Should be 10 + 5.
    ]

    # Initialize a new environment specifically for the lexical interpreter.

    global_env_lexical = ChainedMap()

    do_lexical(global_env_lexical, lexical_program)

    result_lexical = global_env_lexical.get("result")

    print(f"  Result of (10 + 5) with lexical scope: {result_lexical}")

    assert result_lexical == 15

    print("  Lexical scoping test successful.\n")

    # 5. Implicit Sequence

    print("5. Implicit Sequence Test:")

    # This program defines `my_func` whose body is a list of expressions

    # NOT explicitly wrapped in a `["seq", ...]` operator.

    # The `do_implicit` interpreter should automatically recognize this

    # as a sequence and execute its expressions in order.

    implicit_seq_program = [
        "seq",
        [
            "set",
            "my_func",
            [
                "func",
                ["a"],
                [  # Function body is an implicit sequence of two operations
                    ["set", "b", ["add", "a", 1]],  # First: set `b` to `a + 1`
                    [
                        "add",
                        "b",
                        10,
                    ],  # Second: add 10 to `b` (this is the return value)
                ],
            ],
        ],
        ["set", "final_result", ["call", "my_func", 5]],  # Call `my_func` with `a=5`
    ]

    implicit_env = [{}]  # Initialize a new environment for the implicit interpreter.

    do_implicit(implicit_env, implicit_seq_program)

    final_result_implicit = implicit_env[0][
        "final_result"
    ]  # Expected: (5 + 1) + 10 = 16

    print(f"  Result of implicit sequence ((5+1)+10): {final_result_implicit}")

    assert final_result_implicit == 16

    print("  Implicit sequence test successful.\n")

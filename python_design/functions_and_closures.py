# functions_and_closures.py

"""
This file implements the core components for handling functions and their calls
within a simple mini-language interpreter, based on Chapter 8: Functions and Closures
from "Software Design by Example" (https://third-bit.com/sdxpy/func/).

The goal is to demonstrate how a programming system saves instructions for later use
(function definition), how functions are treated as data, and how function calls
manage scope using a call stack.

Key concepts illustrated:
- Anonymous functions: Functions defined without an immediate name.
- Eager evaluation: Arguments are evaluated before a function is called.
- Dynamic scoping: Variables are looked up by searching the entire call stack
  from the most recent frame to the oldest. This is simpler to implement but
  can be harder to reason about in large programs compared to lexical scoping.
- Call stack and stack frames: How environments are managed during function calls.
- Closures (explained in Python context): How inner functions can "capture"
  variables from their enclosing scope, even after the outer function has returned.
  Note: The mini-language interpreter implemented here uses dynamic scoping, 
  so it does not support closures in the same way Python does. The closure
  examples from the text are provided in Python for illustration.
"""

# --- Environment Management ---
# The 'env' in this interpreter is a list of dictionaries, representing the call stack.
# Each dictionary in the list is a 'stack frame'.
# The global environment is the first dictionary in the list (env[0]).
# When a function is called, a new stack frame is pushed onto the list.
# When a function returns, its stack frame is popped off.

def env_get(env_stack: list[dict], name: str):
    """
    Retrieves the value associated with 'name' from the environment stack.
    This implements dynamic scoping: it searches from the most recent stack frame
    (end of the list) backwards to the oldest (global scope).
    """
    for frame in reversed(env_stack):
        if name in frame:
            return frame[name]
    raise NameError(f"Name '{name}' not found in environment.")

def env_set(env_stack: list[dict], name: str, value):
    """
    Sets the value of 'name' in the current (most recent) stack frame.
    If the name already exists in the current frame, its value is updated.
    If it doesn't exist, it's added to the current frame.
    """
    env_stack[-1][name] = value

# --- Function Definition and Call Handlers ---

def _do_func_handler(env_stack: list[dict], args: list):
    """
    Handles the "func" operation, which defines a function.
    In this mini-language, a function definition is treated as data.
    It simply returns a representation of the function: a list containing
    the keyword "func", its parameter names, and its body expression.

    The 'env_stack' argument is part of the general 'do' signature but is
    not directly used here for defining the function's behavior, as this
    interpreter uses dynamic scoping. In a lexical scoping model, the
    environment at the point of definition would be captured here to form a closure.

    Args:
        env_stack: The current environment stack (not used for definition in dynamic scoping).
        args: A list containing two elements:
              - params: A list of strings, representing the parameter names.
              - body: The expression (list) that constitutes the function's body.

    Returns:
        A list representing the function definition: ["func", params, body].
    """
    assert len(args) == 2, "func expects 2 arguments: [params_list, body_expr]"
    params = args[0]  # List of parameter names (e.g., ["num"])
    body = args[1]    # The expression representing the function's body (e.g., ["get", "num"])
    return ["func", params, body]

def _do_call_handler(env_stack: list[dict], args: list):
    """
    Handles the "call" operation, which executes a previously defined function.
    This function is responsible for:
    1. Evaluating arguments (eager evaluation).
    2. Looking up the function by name.
    3. Creating a new stack frame for the function's execution.
    4. Executing the function's body within the new environment.
    5. Discarding the new stack frame upon completion.
    6. Returning the function's result.

    Args:
        env_stack: The current environment stack.
        args: A list where the first element is the function's name (string),
              followed by expressions for its arguments.

    Returns:
        The result of executing the function's body.
    """
    # Step 1: Set up the call.
    assert len(args) >= 1, "call expects at least 1 argument: [function_name, arg1, arg2, ...]"
    name = args[0]  # The name of the function to call (e.g., "same")

    # Evaluate all arguments passed to the function in the *current* environment.
    # This is an example of eager evaluation: arguments are computed before
    # the function's body begins execution.
    values = [do(env_stack, a) for a in args[1:]]

    # Step 2: Find the function.
    # Retrieve the function definition (which is data: ["func", params, body])
    # from the environment using dynamic scoping.
    func = env_get(env_stack, name)
    assert isinstance(func, list) and (func[0] == "func"), f"'{name}' is not a function."

    # Unpack the function definition into its parameters and body.
    params, body = func[1], func[2]

    # Basic type and arity checking.
    assert len(values) == len(params), \
        f"Function '{name}' expected {len(params)} arguments, but got {len(values)}."

    # Step 3: Create a new environment (stack frame) for the function's execution.
    # A new dictionary is created, mapping the function's parameter names to
    # the evaluated argument values. This dictionary becomes the new stack frame.
    # This new frame is then appended to the 'env_stack', making it the active scope.
    # The text mentions an exercise to rewrite this line using a loop;
    # for now, we use the concise built-in functions as provided in the text.
    env_stack.append(dict(zip(params, values)))

    # Step 4: Call 'do' to run the function's body within the new environment.
    # The 'do' function will now look up variables starting from this new stack frame.
    result = do(env_stack, body)

    # Step 5: Discard the environment created in Step 3.
    # After the function's execution, its stack frame is removed from the 'env_stack'.
    # This restores the previous scope, preventing name collisions and cleaning up resources.
    env_stack.pop()

    # Step 6: Return the function's result.
    return result

# --- Main Interpreter Loop (Simplified 'do' function) ---

def do(env_stack: list[dict], expr):
    """
    The main interpreter function. It evaluates an expression within the
    given environment stack. This is a simplified version to support the
    example program from the text.

    Args:
        env_stack: The current environment stack (list of dictionaries).
        expr: The expression to evaluate. Can be a literal (number, string)
              or a list representing an operation.

    Returns:
        The result of evaluating the expression.
    """
    # If the expression is not a list, it's a literal value (e.g., a number).
    if not isinstance(expr, list):
        return expr

    # If it's a list, the first element is the operation, and the rest are arguments.
    op = expr[0]
    args = expr[1:]

    if op == "func":
        # Handle function definition.
        return _do_func_handler(env_stack, args)

    elif op == "call":
        # Handle function call.
        return _do_call_handler(env_stack, args)

    elif op == "set":
        # Assign a value to a variable in the current scope.
        name_to_set = args[0]
        value_expr = args[1]
        value = do(env_stack, value_expr) # Evaluate the value expression
        env_set(env_stack, name_to_set, value)
        return None # 'set' operations typically don't return a meaningful value

    elif op == "get":
        # Retrieve the value of a variable.
        name_to_get = args[0]
        return env_get(env_stack, name_to_get)

    elif op == "add":
        # Perform addition.
        val1 = do(env_stack, args[0])
        val2 = do(env_stack, args[1])
        return val1 + val2

    elif op == "print":
        # Print a value to standard output.
        value_to_print = do(env_stack, args[0])
        print(value_to_print)
        return None

    elif op == "seq":
        # Execute a sequence of expressions, returning the result of the last one.
        result = None
        for sub_expr in args:
            result = do(env_stack, sub_expr)
        return result

    elif op == "repeat":
        # Repeat an expression a specified number of times.
        count = do(env_stack, args[0])
        body_expr = args[1]
        result = None
        for _ in range(count):
            result = do(env_stack, body_expr)
        return result

    else:
        # Raise an error for unsupported operations.
        raise ValueError(f"Unknown operation: {op}")

# --- Example Program from the Text ---

# This program defines a 'double' function, initializes 'a' to 1,
# and then repeats a sequence 4 times:
# 1. Doubles the value of 'a' using the 'double' function.
# 2. Prints the new value of 'a'.
# Expected output: 2, 4, 8, 16
example_program = ["seq",
  ["set", "double",
    ["func", ["num"],
      ["add", ["get", "num"], ["get", "num"]]
    ]
  ],
  ["set", "a", 1],
  ["repeat", 4, ["seq",
    ["set", "a", ["call", "double", ["get", "a"]]],
    ["print", ["get", "a"]]
  ]]
]

# --- Execution ---
if __name__ == "__main__":
    print("--- Running Mini-Language Example Program ---")
    # Initialize the global environment.
    global_frame = {}
    # The environment stack starts with just the global frame.
    interpreter_env = [global_frame]

    # Execute the example program.
    do(interpreter_env, example_program)
    print("--- Program Finished ---")
    print(f"Final global environment: {interpreter_env[0]}")

    print("\n--- Python Closure Examples (from text) ---")
    print("Note: The mini-language interpreter above uses dynamic scoping,")
    print("      and thus does not implement closures in the same way Python does.")
    print("      These examples illustrate lexical scoping and closures in Python.")

    # Example 1: Inner function accessing outer function's variable
    def outer(value):
        def inner(current):
            # 'inner' closes over 'value' from 'outer's scope
            print(f"inner sum is {current + value}")

        print(f"outer value is {value}")
        for i in range(3):
            inner(i)

    print("\n--- Example: Inner function accessing outer scope ---")
    outer(10)

    # Example 2: Returning an inner function (closure)
    def make_hidden(thing):
        def _inner():
            # '_inner' closes over 'thing'
            return thing
        return _inner

    print("\n--- Example: Returning a closure ---")
    has_secret = make_hidden(1 + 2)
    print("hidden thing is", has_secret()) # 'has_secret' still remembers 'thing' (which is 3)

    # Example 3: Implementing objects using closures
    def make_object(initial_value):
        # 'private' dictionary is closed over by getter and setter
        private = {"value": initial_value}

        def getter():
            return private["value"]

        def setter(new_value):
            private["value"] = new_value

        return {"get": getter, "set": setter}

    print("\n--- Example: Object-like behavior with closures ---")
    obj = make_object(0) # Note: Changed from 00 to 0 for clarity, 00 is octal in some contexts
    print("initial value", obj["get"]())
    obj["set"](99)
    print("object now contains", obj["get"]())

    # Example 4: What can change? (Illustrating Python's variable capture rules)
    # This example from the text highlights a common pitfall with closures in Python
    # when trying to modify a variable from an enclosing scope directly.

    print("\n--- Example: Python's variable capture rules (make_counter) ---")

    # This version fails because 'value' in _inner is treated as a local variable
    # when assigned to, but it's not defined locally. Python 3 requires 'nonlocal'
    # for modifying enclosing scope variables.
    # def make_counter_failing():
    #     value = 0
    #     def _inner():
    #         value += 1 # UnboundLocalError: local variable 'value' referenced before assignment
    #         return value
    #     return _inner

    # print("\nFailing counter (commented out to prevent error):")
    # c_failing = make_counter_failing()
    # try:
    #     for i in range(3):
    #         print(c_failing())
    # except UnboundLocalError as e:
    #     print(f"Error: {e} (as expected)")

    # This version works by using a mutable list to hold the value.
    # The list itself is captured, and its contents can be modified.
    def make_counter_working():
        value = [0] # 'value' is a list, which is mutable
        def _inner():
            value[0] += 1 # Modifying the element of the captured list
            return value[0]
        return _inner

    print("\nWorking counter:")
    c_working = make_counter_working()
    for i in range(3):
        print(c_working())

    # Example 5: How private are closures? (Illustrating shared mutable state)
    print("\n--- Example: Shared mutable state in closures ---")

    def wrap(extra):
        def _inner(f):
            # _inner closes over 'extra'. If 'extra' is mutable and modified
            # outside, the closure will see the changes.
            return [f(x) for x in extra]
        return _inner

    odds = [1, 3, 5]
    first = wrap(odds)
    print("1.", first(lambda x: 2 * x)) # Uses [1, 3, 5] -> [2, 6, 10]

    odds = [7, 9, 11] # 'odds' is reassigned, but 'first' still holds a reference to the *original* list [1, 3, 5]
    print("2.", first(lambda x: 2 * x)) # Still uses [1, 3, 5] -> [2, 6, 10]
    # Explanation: Python's closure captures the *reference* to the list object
    # that 'odds' pointed to at the time 'wrap' was called. Reassigning 'odds'
    # to a new list does not change the object that 'first' (via its closure) refers to.

    evens = [2, 4, 6]
    second = wrap(evens)
    print("3.", second(lambda x: 2 * x)) # Uses [2, 4, 6] -> [4, 8, 12]

    evens.append(8) # The *same list object* that 'second' captured is modified
    print("4.", second(lambda x: 2 * x)) # Now uses [2, 4, 6, 8] -> [4, 8, 12, 16]
    # Explanation: Here, 'evens.append(8)' modifies the list object *in place*.
    # Since 'second's closure holds a reference to this exact list object,
    # it sees the modification. This demonstrates that closures capture references,
    # and if the referenced object is mutable, changes to it are visible through the closure.

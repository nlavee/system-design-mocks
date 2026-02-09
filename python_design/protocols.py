# protocols.py

"""
This file implements several fundamental Python protocols as described in
Chapter 9: Protocols from "Software Design by Example" (https://third-bit.com/sdxpy/protocols/).

The goal is to provide clear, commented examples of how these protocols work,
enabling a deeper understanding of Python's inner mechanics.

Key protocols and concepts illustrated:
- Mock Objects: Using callable objects (`__call__`) to create test doubles.
- Context Managers: Ensuring setup and teardown operations with `with` statements
  (`__enter__` and `__exit__`).
- Decorators: Wrapping functions to add functionality, using closures and decorators
  with arguments.
- Iterators: The mechanism behind `for` loops (`__iter__` and `__next__`).
"""

import time
import random

# --- Section 9.1: Mock Objects ---
# Mock objects are test doubles that replace real components for testing purposes.
# This section demonstrates how to build a simple mocking utility using Python's
# `__call__` protocol, which allows an object to be called like a function.

class Fake:
    """
    A simple mock object class that can replace a function for testing.
    It records calls made to it and can return either a fixed value or a
    value computed by a provided function.
    """
    def __init__(self, returns=None, side_effect=None):
        """
        Initializes the Fake object.

        Args:
            returns: The fixed value to return when the fake is called.
            side_effect: A function to call to compute the return value.
                         This is useful for simulating more complex behavior.
        """
        self.calls = []  # A list to store the arguments of each call.
        self._returns = returns
        self._side_effect = side_effect

    def __call__(self, *args, **kwargs):
        """
        This method is executed when an instance of Fake is called like a function.
        It records the call's arguments and determines the return value.
        """
        # Record the arguments for this call.
        self.calls.append((args, kwargs))

        # Determine the return value. If a side_effect function is provided,
        # call it. Otherwise, return the fixed `_returns` value.
        if self._side_effect:
            return self._side_effect(*args, **kwargs)
        return self._returns

# --- Section 9.2: Context Managers ---
# The context management protocol enables the use of `with` statements, which
# guarantee that setup and teardown logic is executed. A class must implement
# `__enter__` (for setup) and `__exit__` (for teardown).

class ContextFake(Fake):
    """
    A context manager that temporarily replaces a global function with a fake
    and automatically restores the original function upon exiting the `with` block.
    """
    def __init__(self, target_module, function_name, **kwargs):
        """
        Initializes the context-aware fake.

        Args:
            target_module: The module containing the function to be replaced
                           (e.g., the `time` module).
            function_name: The string name of the function to replace (e.g., "sleep").
            **kwargs: Arguments to pass to the parent Fake's constructor
                      (e.g., `returns` or `side_effect`).
        """
        super().__init__(**kwargs)
        self._module = target_module
        self._func_name = function_name
        self._original_func = None

    def __enter__(self):
        """
        The setup method for the context manager, executed at the start of the `with` block.
        It saves the original function and replaces it with this fake object.
        """
        # Store the original function from the target module.
        self._original_func = getattr(self._module, self._func_name)
        # Replace the function in the module with this object. Because this object
        # has a `__call__` method, it can be used just like the original function.
        setattr(self._module, self._func_name, self)
        return self  # The value returned here is assigned to the `as` variable in the `with` statement.

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        The teardown method, executed when the `with` block is exited.
        It restores the original function, ensuring the system is returned to its
        original state, even if an error occurred inside the `with` block.
        """
        # Restore the original function to the target module.
        setattr(self._module, self._func_name, self._original_func)

# Example usage of ContextFake
def go_to_sleep(duration):
    """A simple function that uses time.sleep."""
    print(f"Sleeping for {duration} seconds...")
    time.sleep(duration)
    print("Awake!")

# --- Section 9.3: Decorators ---
# Decorators provide a concise syntax for wrapping one function with another.
# This is a powerful tool for adding functionality like logging, timing, or
# access control without modifying the original function's code.

def timer(func):
    """
    A simple decorator that measures and prints the execution time of a function.
    It demonstrates the core concept of a decorator: a function that takes a
    function as input and returns a new (wrapped) function.
    """
    def wrapper(*args, **kwargs):
        # The wrapper function is what actually gets called. It "closes over"
        # the `func` variable from the decorator's scope.
        start = time.time()
        result = func(*args, **kwargs) # Call the original function
        end = time.time()
        print(f"Execution of '{func.__name__}' took {end - start:.4f} seconds.")
        return result
    return wrapper

# Decorator with arguments
def retry(max_attempts):
    """
    A decorator that retries a function call up to `max_attempts` times if it fails.
    To accept arguments, the decorator needs an extra layer of nesting:
    1. `retry(max_attempts)`: This outer function receives the decorator's arguments
       and returns the actual decorator.
    2. `decorator(func)`: This is the decorator, which takes the function to be
       wrapped and returns the final wrapper function.
    3. `wrapper(*args, **kwargs)`: This is the function that gets executed,
       containing the retry logic.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs) # Attempt to call the original function
                except Exception as e:
                    print(f"Attempt {attempt + 1}/{max_attempts} failed: {e}")
                    if attempt + 1 == max_attempts:
                        print("All attempts failed.")
                        raise # Re-raise the last exception
        return wrapper
    return decorator

# Example function using decorators
@timer
@retry(max_attempts=3)
def possibly_fail():
    """A function that might fail randomly."""
    if random.random() < 0.5:
        raise ValueError("Random failure!")
    print("Function succeeded.")

# --- Section 9.4: Iterators ---
# The iterator protocol is what powers `for` loops in Python. An object that
# wants to be iterable must implement `__iter__`, which returns an iterator object.
# The iterator object must implement `__next__`, which returns items until it
# raises `StopIteration`.

class SimpleRange:
    """A simple implementation of a range-like iterator."""
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self._current = start

    def __iter__(self):
        # In this simple case, the object is its own iterator.
        # It already has a `__next__` method.
        return self

    def __next__(self):
        # Return the next item in the sequence.
        if self._current >= self.end:
            # Signal that the iteration is complete.
            raise StopIteration
        value = self._current
        self._current += 1
        return value

class BetterRange:
    """
    An improved iterator design that separates the iterable collection from the
    iterator state (the "cursor"). This allows multiple independent `for` loops
    to run over the same collection.
    """
    def __init__(self, start, end):
        """The main object only stores the range's configuration."""
        self.start = start
        self.end = end

    def __iter__(self):
        """
        Returns a new, separate iterator object (a "cursor") each time it's called.
        This ensures that each `for` loop gets its own state.
        """
        return RangeCursor(self.start, self.end)

class RangeCursor:
    """
    The iterator object ("cursor") that holds the state for a single iteration.
    """
    def __init__(self, start, end):
        self._current = start
        self._end = end

    def __next__(self):
        if self._current >= self._end:
            raise StopIteration
        value = self._current
        self._current += 1
        return value

# --- Execution of Examples ---
if __name__ == "__main__":
    print("--- 9.1: Mock Objects & 9.2: Context Managers ---")
    print("Running `go_to_sleep` normally:")
    go_to_sleep(0.1)

    print("\nRunning `go_to_sleep` with a context manager to fake `time.sleep`:")
    # The `with` statement ensures that time.sleep is replaced only within this block.
    with ContextFake(time, "sleep", returns=None) as fake_sleep:
        go_to_sleep(0.1)
    # Check that the fake recorded the call correctly.
    print(f"Fake was called with: {fake_sleep.calls}")
    # Verify that `time.sleep` has been restored to its original state.
    print(f"Is time.sleep the fake object anymore? {time.sleep is fake_sleep}")

    print("\n--- 9.3: Decorators ---")
    print("Running a function with @timer and @retry decorators:")
    try:
        possibly_fail()
    except ValueError:
        print("Caught expected failure after retries.")

    print("\n--- 9.4: Iterators ---")
    print("Iterating with SimpleRange (single loop):")
    for i in SimpleRange(0, 3):
        print(i)

    print("\nIterating with BetterRange (nested loops):")
    # Because BetterRange creates a new cursor for each loop, this works as expected.
    # If SimpleRange were used here, the inner loop would exhaust the iterator,
    # and the outer loop would not continue.
    r = BetterRange(0, 2)
    for i in r:
        for j in r:
            print(f"({i}, {j})")

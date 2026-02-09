import time
import sys

# Core Concepts of this Testing Framework:
# 1. Test Discovery: Using globals() to find functions starting with "test_".
# 2. Categorization: Distinguishing between Pass, Fail (AssertionError), and Error (other Exceptions).
# 3. Life Cycle: Using setup() and teardown() to manage test state.
# 4. Instrumentation: Measuring time and filtering tests by name.

def run_tests(pattern=None):
    """
    Discovers and runs tests in the current global scope.
    
    Reasoning for 'pattern' parameter:
    This satisfies Exercise 5. In a real CLI tool, we would use sys.argv to populate this.
    Allowing a pattern enables developers to focus on specific components during development.
    """
    
    # Discovery phase
    # globals() returns a dictionary of the current global symbol table.
    # We iterate over it to find test candidates.
    all_names = sorted(globals().keys())
    
    # We need to capture setup/teardown if they exist (Exercise 3)
    setup_func = globals().get("setup")
    teardown_func = globals().get("teardown")
    
    results = {
        "pass": [],
        "fail": [],
        "error": []
    }
    
    start_all = time.time()
    
    for name in all_names:
        # Exercise 6: Ensure we only run things that start with test_ AND are callable.
        # Reasoning: A user might define a variable like test_data = [1, 2, 3].
        # Attempting to call that would raise a TypeError.
        obj = globals()[name]
        if name.startswith("test_") and callable(obj):
            
            # Exercise 5: Pattern matching selection
            if pattern and pattern not in name:
                continue
                
            # Exercise 3: Setup before each test
            if setup_func and callable(setup_func):
                setup_func()
                
            print(f"Running {name}...", end=" ", flush=True)
            
            # Exercise 4: Timing (Start)
            start_test = time.time()
            
            try:
                obj() # Execute the test
                duration = time.time() - start_test
                print(f"PASS ({duration:.4f}s)")
                results["pass"].append(name)
            except AssertionError as e:
                # Exercise 2: Report specific failures
                duration = time.time() - start_test
                print(f"FAIL ({duration:.4f}s): {e}")
                results["fail"].append(name)
            except Exception as e:
                # Exercise 2: Report specific errors
                duration = time.time() - start_test
                print(f"ERROR ({duration:.4f}s): {type(e).__name__}: {e}")
                results["error"].append(name)
            finally:
                # Exercise 3: Teardown after each test (regardless of outcome)
                if teardown_func and callable(teardown_func):
                    teardown_func()
                    
    end_all = time.time()
    
    # Exercise 2: Summary Report
    print("-" * 30)
    print(f"Ran {len(results['pass']) + len(results['fail']) + len(results['error'])} tests in {end_all - start_all:.4f}s")
    print(f"Passed: {len(results['pass'])}")
    print(f"Failed: {len(results['fail'])}")
    print(f"Errors: {len(results['error'])}")
    
    if results["fail"] or results["error"]:
        print("\nDetails:")
        for name in results["fail"]:
            print(f"[FAIL] {name}")
        for name in results["error"]:
            print(f"[ERR ] {name}")

# --- Example Usage and Exercises Demo ---

# Global variable to demonstrate setup/teardown
_TEST_STATE = None

def setup():
    """Reasoning: Initialize shared state so tests start from a clean baseline."""
    global _TEST_STATE
    _TEST_STATE = []

def teardown():
    """Reasoning: Cleanup resources or reset state to avoid side-effects between tests."""
    global _TEST_STATE
    _TEST_STATE = None

def test_passing_example():
    _TEST_STATE.append(1)
    assert len(_TEST_STATE) == 1

def test_failing_example():
    """This will be categorized as a FAIL because of AssertionError."""
    assert 1 == 2, "Expected 1 to equal 2"

def test_error_example():
    """This will be categorized as an ERROR because it raises a non-AssertionError."""
    return 1 / 0

# Exercise 6: Non-callable object with test_ prefix
test_data_variable = "I am not a function"

def test_slow_example():
    """Demonstrates timing reporting."""
    time.sleep(0.1)
    assert True

if __name__ == "__main__":
    # If a pattern is provided as a CLI argument, use it.
    # Usage: python test_framework_ex.py example
    pattern = sys.argv[1] if len(sys.argv) > 1 else None
    run_tests(pattern)

# --- Discussion on Exercise 7 (Local Variables) ---
# When you call a function, Python creates a local symbol table (locals()).
# In the exercise 'show_locals(1, 3)':
# 1. Arguments 'a' and 'b' are in locals() immediately.
# 2. 'i' appears in locals() as soon as the 'for' loop starts.
# 3. In Python, loop variables (like 'i') LEAK into the function's local scope 
#    and persist after the loop finishes.

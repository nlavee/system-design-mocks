# interpreter_enhancements.py

"""
This file implements solutions to the "Chained Maps" and "Implicit Sequence"
exercises from Chapter 8 of "Software Design by Example" (https://third-bit.com/sdxpy/func/).

These exercises introduce more advanced and efficient ways to structure the interpreter,
moving towards a more realistic implementation of lexical scoping and improving
the language's ergonomics.
"""

# --- Exercise: Chained Maps for Environments ---
class ChainedMap:
    """
    An environment implementation using chained maps (a linked list of scopes).
    Each instance represents a single scope (or stack frame).
    """
    def __init__(self, parent=None):
        self.frame = {}
        self.parent = parent

    def get(self, name: str):
        if name in self.frame:
            return self.frame[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"Name '{name}' not found in environment.")

    def set(self, name: str, value):
        self.frame[name] = value

def do_chained(env: ChainedMap, expr):
    """
    An interpreter main loop that operates on ChainedMap environments,
    supporting lexical scoping and closures.
    """
    if not isinstance(expr, list):
        if isinstance(expr, str) and expr.isidentifier():
            try:
                return env.get(expr)
            except NameError:
                return expr
        return expr

    op = expr[0]
    args = expr[1:]

    if op == "set":
        name, value_expr = args[0], args[1]
        value = do_chained(env, value_expr)
        env.set(name, value)
        return None
    if op == "func":
        params, body = args[0], args[1]
        return ["closure", params, body, env]
    if op == "call":
        func_expr = args[0]
        closure = do_chained(env, func_expr)
        
        if isinstance(closure, str) and closure.isidentifier():
             closure = env.get(closure)

        closure_type, params, body, definition_env = closure
        assert closure_type == "closure", f"'{func_expr}' is not a function."

        arg_values = [do_chained(env, arg) for arg in args[1:]]
        call_env = ChainedMap(parent=definition_env)
        
        assert len(params) == len(arg_values), f"Function arity mismatch for {func_expr}"

        for i in range(len(params)):
            call_env.set(params[i], arg_values[i])
        
        if isinstance(body, list) and len(body) > 0 and isinstance(body[0], list):
            result = None
            for sub_expr in body:
                result = do_chained(call_env, sub_expr)
            return result
        else:
            return do_chained(call_env, body)

    if op == "add":
        return do_chained(env, args[0]) + do_chained(env, args[1])
    if op == "print":
        print(do_chained(env, args[0]))
        return None
    if op == "seq":
        result = None
        for sub_expr in args:
            result = do_chained(env, sub_expr)
        return result

    raise ValueError(f"Unknown operation: {op}")


# --- Exercise: Implicit Sequence (in a simpler, dynamic-scoped interpreter) ---

def do_implicit(env_stack: list, expr):
    """
    An interpreter that handles implicit sequences in a dynamically-scoped context.
    """
    def env_get(name):
        for frame in reversed(env_stack):
            if name in frame: return frame[name]
        raise NameError(f"Name '{name}' not found")

    def env_set(name, value):
        env_stack[-1][name] = value

    if not isinstance(expr, list):
        if isinstance(expr, str) and expr.isidentifier():
            try:
                return env_get(expr)
            except NameError:
                return expr
        return expr

    if len(expr) > 0 and isinstance(expr[0], list):
        result = None
        for sub_expr in expr:
            result = do_implicit(env_stack, sub_expr)
        return result

    op = expr[0]
    args = expr[1:]

    if op == "set":
        env_set(args[0], do_implicit(env_stack, args[1]))
        return None
    if op == "get":
        return env_get(args[0])
    if op == "add":
        return do_implicit(env_stack, args[0]) + do_implicit(env_stack, args[1])
    if op == "func":
        return ["func", args[0], args[1]]
    if op == "call":
        func = env_get(args[0])
        params, body = func[1], func[2]
        values = [do_implicit(env_stack, a) for a in args[1:]]
        
        new_frame = dict(zip(params, values))
        env_stack.append(new_frame)
        
        result = do_implicit(env_stack, body)
        
        env_stack.pop()
        return result
    if op == "seq":
        result = None
        for sub_expr in args:
            result = do_implicit(env_stack, sub_expr)
        return result

    raise ValueError(f"Unknown operation: {op}")


# --- Execution of Examples ---
if __name__ == "__main__":
    print("--- Exercise: Chained Maps (Lexical Scoping) ---")
    lexical_program = ["seq",
        ["set", "make_adder",
            ["func", ["n"],
                ["func", ["x"],
                    ["add", "x", "n"]
                ]
            ]
        ],
        ["set", "add_five", ["call", "make_adder", 5]],
        ["set", "result", ["call", "add_five", 10]],
    ]
    global_env_chained = ChainedMap()
    print("Running lexical scope program:")
    do_chained(global_env_chained, lexical_program)
    result = global_env_chained.get("result")
    print(f"Result of lexical scope test (10 + 5): {result}")
    assert result == 15
    print("Lexical scoping with Chained Maps successful.")

    print("\n--- Exercise: Implicit Sequence ---")
    # This program now uses 'get' for clarity, although the interpreter can handle bare words.
    implicit_seq_program = ["seq",
      ["set", "my_func",
        ["func", ["a"], [ # Body is an implicit sequence
            ["set", "b", ["add", ["get", "a"], 1]],
            ["add", ["get", "b"], 10]
        ]]
      ],
      ["set", "final_result", ["call", "my_func", 5]]
    ]
    implicit_env = [{}]
    print("Running implicit sequence program:")
    do_implicit(implicit_env, implicit_seq_program)
    final_result = implicit_env[0]["final_result"]
    print(f"Result of implicit sequence test: {final_result}")
    assert final_result == 16
    print("Implicit sequence handling successful.")

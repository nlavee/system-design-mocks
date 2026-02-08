# Pattern Matcher 
# Similar to file matching glob program, but much simpler.
# https://third-bit.com/sdxpy/glob/

# Parent class for matching patterns.
# This should return the substr that matched each part of the expression.
class Matcher():
  def __init__(self, rest=None):
    self.rest = rest if rest else Null()

  def match(self, text):
    res = self._match(text, 0)
    if res is None:
      return None
    final_end, matches = res
    if final_end == len(text):
      return matches
    return None


# Matching nothing, used to signify the end.
class Null(Matcher):
  def __init__(self):
    self.rest = None
 
  def _match(self, text, start):
    return (start, [])


# Matching literal
class Lit(Matcher):
  def __init__(self, chars, rest=None):
    super().__init__(rest)
    self.chars = chars

  def _match(self, text, start):
    end = start + len(self.chars)
    if self.chars != text[start:end]:
      return None
    res = self.rest._match(text, end)
    if res is None:
      return None
    next_end, matches = res
    return (next_end, [self.chars] + matches)


# Matching Any
class Any(Matcher):
  def __init__(self,  rest=None):
    super().__init__(rest)
    self._rest_cache = {}
    self._last_text_id = None
 
  def _match(self, text, start):
    if id(text) != self._last_text_id:
      self._last_text_id = id(text)
      self._rest_cache = {}

    for i in range(start, len(text)+1):
      if i not in self._rest_cache:
        self._rest_cache[i] = self.rest._match(text, i)

      res = self._rest_cache[i]
      if res is not None:
        next_end, matches = res
        if next_end == len(text):
          matched_here = text[start:i]
          return (next_end, [matched_here] + matches)
    return None


# Matching Either
class Either(Matcher):
  def __init__(self, sub_patterns, rest=None):
    super().__init__(rest)
    self._sub_patterns = sub_patterns

  def _match(self, text, start):
    if not self._sub_patterns:
      return self.rest._match(text, start)

    for pat in self._sub_patterns:
      res = pat._match(text, start)
      if res is not None:
        end, _ = res
        final_res = self.rest._match(text, end)
        if final_res is not None:
          final_end, rest_matches = final_res
          if final_end == len(text):
            matched_here = text[start:end]
            return (final_end, [matched_here] + rest_matches)
    return None

  
# Matching One or more (greedy-approach, will try to match as much as possible).
# Equivalent to "+" matching
class OneOrMore(Matcher):
  def __init__(self, chars, rest=None):
    super().__init__(rest)
    self.chars = chars

  def _match(self, text, start):
    if not self.chars:
      return self.rest._match(text, start)

    # Collect all positions where we have matched at least one 'chars'
    positions = []
    current = start
    while current + len(self.chars) <= len(text):
      if text[current:current+len(self.chars)] == self.chars:
        current += len(self.chars)
        positions.append(current)
      else:
        break
    
    # Greedy backtracking: try the longest matches first
    for pos in reversed(positions):
      res = self.rest._match(text, pos)
      if res is not None:
        next_end, matches = res
        matched_here = text[start:pos]
        return (next_end, [matched_here] + matches)
        
    return None


# Matching Any from Set. E.g. Charset('aeiou') matches any lower-case vowel.
class Charset(Matcher):
  def __init__(self, chars, rest=None):
    super().__init__(rest)
    self.charSet = set([c for c in chars])


  def _match(self, text, start):
    if start < len(text) and text[start] in self.charSet:
      res = self.rest._match(text, start + 1)
      if res is not None:
        next_end, matches = res
        return (next_end, [text[start]] + matches)
    return None


# Matching range of character. E.g. Range("a", "z") matches any single lower case Latin alphabetic character.
class Range(Matcher):
  def __init__(self, range_start, range_end, rest=None):
    super().__init__(rest)
    self.range_start = ord(range_start)
    self.range_end = ord(range_end)


  def _match(self, text, start):
    if start < len(text) and self.range_start <= ord(text[start]) <= self.range_end:
      res = self.rest._match(text, start + 1)
      if res is not None:
        next_end, matches = res
        return (next_end, [text[start]] + matches)
    return None


# Matcher that doesn't match a specified pattern.
# For example, Not(Lit("abc")) only succeeds if the text isn't "abc".
class Not(Matcher):
  def __init__(self, negated_pat, rest=None):
    super().__init__(rest)
    self.negated_pat = negated_pat
    

  def _match(self, text, start):
    # If the negated pattern matches, then 'Not' fails.
    if self.negated_pat._match(text, start) is not None:
      return None
    
    # Use the same logic as Any: find a position that matches rest until the end.
    for i in range(start, len(text) + 1):
      res = self.rest._match(text, i)
      if res is not None:
        final_end, matches = res
        if final_end == len(text):
          matched_here = text[start:i]
          return (final_end, [matched_here] + matches)
    return None


def test_case_matcher_str():
  # test cases
  m = Any(Lit(".txt"))
  res = m.match("name.txt")
  assert res == ["name", ".txt"]
  print(f"Any(Lit('.txt')) matched 'name.txt': {res}")

  m = Either([Lit("a"), Lit("b")], Lit("c"))
  res = m.match("ac")
  assert res == ["a", "c"]
  print(f"Either([Lit('a'), Lit('b')], Lit('c')) matched 'ac': {res}")
  
  m = OneOrMore("a", Lit("b"))
  res = m.match("aaab")
  assert res == ["aaa", "b"]
  print(f"OneOrMore('a', Lit('b')) matched 'aaab': {res}")

  m = Lit("x", Not(Lit("y"), Lit("z")))
  res = m.match("xz")
  assert res == ["x", "", "z"]
  print(f"Lit('x', Not(Lit('y'), Lit('z'))) matched 'xz': {res}")

  # More tests
  # Null
  m = Null()
  assert m.match("") == []
  assert m.match("a") is None
  print("Null tests passed")

  # Lit
  m = Lit("abc")
  assert m.match("abc") == ["abc"]
  assert m.match("abd") is None
  assert m.match("abcd") is None
  print("Lit tests passed")

  # Any
  m = Any()
  assert m.match("") == [""]
  assert m.match("anything") == ["anything"]
  m = Lit("p", Any(Lit("q")))
  assert m.match("p...q") == ["p", "...", "q"]
  print("Any tests passed")

  # Either
  m = Either([Lit("apple"), Lit("banana")])
  assert m.match("apple") == ["apple"]
  assert m.match("banana") == ["banana"]
  assert m.match("cherry") is None
  print("Either tests passed")

  # OneOrMore
  m = OneOrMore("ab")
  assert m.match("ababab") == ["ababab"]
  assert m.match("aba") is None
  assert m.match("") is None
  print("OneOrMore tests passed")

  # Charset
  m = Charset("aeiou", Lit("!"))
  assert m.match("a!") == ["a", "!"]
  assert m.match("e!") == ["e", "!"]
  assert m.match("x!") is None
  print("Charset tests passed")

  # Range
  m = Range("0", "9", Lit(" units"))
  assert m.match("5 units") == ["5", " units"]
  assert m.match("a units") is None
  print("Range tests passed")

  # Not
  m = Not(Lit("bad"), Any())
  assert m.match("good string") == ["", "good string"]
  assert m.match("bad string") is None
  print("Not tests passed")

  # Complex Combination
  # Pattern: [a-z]+[0-9] followed by either ".png" or ".jpg"
  m = OneOrMore("a") # Simplified for this demo to just 'a's
  m = Range("a", "z", OneOrMore("a", Range("0", "9", Either([Lit(".png"), Lit(".jpg")]))))
  # This is getting complex, let's try a simpler combined one:
  # (a|b)+ followed by '.' then 3 digits
  m = OneOrMore("a", Lit(".", Range("0", "9", Range("0", "9", Range("0", "9")))))
  res = m.match("aaa.123")
  assert res == ["aaa", ".", "1", "2", "3"]
  print(f"Complex pattern matched 'aaa.123': {res}")

if __name__ == "__main__":
  test_case_matcher_str()

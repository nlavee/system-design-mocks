# Pattern Matcher 
# Similar to file matching glob program, but much simpler.
# https://third-bit.com/sdxpy/glob/

# Parent class for matching patterns.
class Matcher():
  def __init__(self, rest=None):
    self.rest = rest if rest else Null()

  def match(self, text):
    matched_position = self._match(text, 0)
    return matched_position == len(text)


# Matching nothing, used to signify the end.
class Null(Matcher):
  def __init__(self):
    self.rest = None
 
  def _match(self, text, start):
    return start


# Matching literal
class Lit(Matcher):
  def __init__(self, chars, rest=None):
    super().__init__(rest)
    self.chars = chars

  def _match(self, text, start):
    end = start + len(self.chars)
    if self.chars != text[start:end]:
      return None
    return self.rest._match(text, end)


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

      result = self._rest_cache[i]
      if result == len(text):
        return result
    return None


# Matching Either
class Either(Matcher):
  def __init__(self, sub_patterns, rest=None):
    super().__init__(rest)
    self._sub_patterns = sub_patterns

  def _match(self, text, start):
    if not self._sub_patterns:
      return len(text)

    for pat in self._sub_patterns:
      end = pat._match(text, start)
      if end is not None:
        end = self.rest._match(text, end)
        if end == len(text):
          return end
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
        return res
        
    return None


# Matching Any from Set. E.g. Charset('aeiou') matches any lower-case vowel.
class Charset(Matcher):
  def __init__(self, chars, rest=None):
    super().__init__(rest)
    self.charSet = set([c for c in chars])


  def _match(self, text, start):
    if start < len(text) and text[start] in self.charSet:
      return self.rest._match(text, start + 1)
    return None


# Matching range of character. E.g. Range("a", "z") matches any single lower case Latin alphabetic character.
class Range(Matcher):
  def __init__(self, range_start, range_end, rest=None):
    super().__init__(rest)
    self.range_start = ord(range_start)
    self.range_end = ord(range_end)


  def _match(self, text, start):
    if start < len(text) and self.range_start <= ord(text[start]) <= self.range_end:
      return self.rest._match(text, start + 1)
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
      if res == len(text):
        return res
    return None


def test_case_matcher_bool():
  # test cases
  assert Either([Lit("a"), Lit("b")]).match("a")
  assert not Either([Lit("a"), Lit("b")]).match("ab")
  assert not Either([Lit("a"), Lit("b"), Lit("abacus")]).match("ab")
  assert Either([Lit("a"), Lit("b"), Lit("c")]).match("c")
  assert OneOrMore("a").match("a")
  assert OneOrMore("a", OneOrMore("a")).match("aa")
  assert OneOrMore("a", OneOrMore("a", Lit("a"))).match("aaa")
  assert not OneOrMore("a", OneOrMore("a", Lit("a"))).match("aa")
  assert not OneOrMore("a", OneOrMore("a")).match("a")
  assert OneOrMore("a", Lit("b")).match("aaaaaaaab")
  assert OneOrMore("a", Lit("b")).match("ab")
  assert not OneOrMore("a", Lit("b")).match("aaaaacb")
  assert not OneOrMore("a", Any(Lit("b"))).match("aaaaa")
  assert OneOrMore("a", Any(Lit("b"))).match("aaaaab")
  assert OneOrMore("a", OneOrMore("b", Lit("b", Any()))).match("aaaaabbb")
  assert OneOrMore("a", OneOrMore("b", Lit("b", Any()))).match("abbb")
  assert not OneOrMore("a", OneOrMore("b", Lit("b", Any()))).match("aaaaaba")
  assert OneOrMore("a", OneOrMore("b", Lit("b", Any()))).match("aaaaabbbbbbbbbba")

  assert Charset("abc", OneOrMore("b", Lit("b", Any()))).match("abbbbbbbbbba")
  assert not Charset("z", OneOrMore("b", Lit("b", Any()))).match("abbbbbbbbbba")
  assert not Charset("", OneOrMore("b", Lit("b", Any()))).match("abbbbbbbbbba")

  assert Range("a", "z").match("r")
  assert Range("a", "c", Charset("def", OneOrMore("b", Lit("b", Any())))).match("bdbbbbbb")
  assert Range("a", "c", Charset("def", OneOrMore("b", Lit("b", Any())))).match("bdbb0")
  assert Range("a", "c", Charset("def", OneOrMore("b", Lit("b", Any())))).match("aebb0")
  assert not Range("a", "c", Charset("def", OneOrMore("b", Lit("b", Any())))).match("aeb0")


  assert Not(Lit("abc")).match("d")
  assert not Not(Lit("abc")).match("abc")
  assert Lit("x", Not(Lit("y"))).match("xz")
  assert Lit("x", Not(Lit("y", Lit("z")))).match("xz")


if __name__ == "__main__":
  test_case_matcher_bool()

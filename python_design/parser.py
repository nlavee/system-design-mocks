# Parser
import string
from pattern_matcher import Matcher, Null, Lit, Any, Either, Charset, NegatedCharset

CHARS = set(string.ascii_letters + string.digits)

class Tokenizer():
  def __init__(self):
    self._setup()

  def _setup(self):
    self.result = []
    self.current = ""
  
  def tok(self, text):
    self._setup()
    escaping = False
    for ch in text:
      if escaping:
        self.current += ch
        escaping = False
      elif ch == "\\":
        escaping = True
      elif ch == "*":
        self._add("Any")
      elif ch == "{":
        self._add("EitherStart")
      elif ch == ",":
        self._add(None)
      elif ch == "}":
        self._add("EitherEnd")
      elif ch == "[":
        self._add("CharsetStart")
      elif ch == "]":
        self._add("CharsetEnd")
      elif ch in CHARS or ch == "!":
        self.current += ch
      else:
        raise NotImplementedError(f"What is '{ch}'?")
    self._add(None)
    return self.result


  def _add(self, thing):
    if len(self.current) > 0:
      self.result.append(["Lit", self.current])
      self.current = ""
    if thing is not None:
      self.result.append([thing])


def test_tok_empty_string():
  assert Tokenizer().tok("") == []


def test_tok_any_either():
  assert Tokenizer().tok("*{abc,def}") == [
    ["Any"],
    ["EitherStart"],
    ["Lit", "abc"],
    ["Lit", "def"],
    ["EitherEnd"],
  ]


def test_tok_escape():
  assert Tokenizer().tok("\\*a\\[") == [
    ["Lit", "*a["],
  ]


def test_tok_charset():
  assert Tokenizer().tok("[abc][!def]") == [
    ["CharsetStart"],
    ["Lit", "abc"],
    ["CharsetEnd"],
    ["CharsetStart"],
    ["Lit", "!def"],
    ["CharsetEnd"],
  ]


def test_parse_simple():
  tokens = Tokenizer().tok("a*b")
  matcher = Parser()._parse(tokens)
  assert matcher.match("axxxb")
  assert not matcher.match("axxx")


def test_parse_charset():
  tokens = Tokenizer().tok("[abc]x")
  matcher = Parser()._parse(tokens)
  assert matcher.match("ax")
  assert matcher.match("bx")
  assert not matcher.match("dx")


def test_parse_negated_charset():
  tokens = Tokenizer().tok("[!abc]x")
  matcher = Parser()._parse(tokens)
  assert matcher.match("dx")
  assert not matcher.match("ax")


def test_parse_escape():
  tokens = Tokenizer().tok("\\*x")
  matcher = Parser()._parse(tokens)
  assert matcher.match("*x")
  assert not matcher.match("ax")


class Parser():

  def _parse(self, tokens):
    if not tokens:
      return Null()

    front, back = tokens[0], tokens[1:]
    if front[0] == "Any": handler = self._parse_Any
    elif front[0] == "EitherStart": handler = self._parse_EitherStart
    elif front[0] == "CharsetStart": handler = self._parse_CharsetStart
    elif front[0] == "Lit": handler = self._parse_Lit
    else:
      assert False, f"Unknown token type {front}"

    return handler(front[1:], back)


  def _parse_Any(self, rest, back):
    return Any(self._parse(back))


  def _parse_Lit(self, rest, back):
    return Lit(rest[0], self._parse(back))


  def _parse_EitherStart(self, rest, back):
    if (
      len(back) < 3
      or (back[0][0] != "Lit")
      or (back[1][0] != "Lit")
      or (back[2][0] != "EitherEnd")
    ):
      raise ValueError("badly-formatted Either")

    left = Lit(back[0][1])
    right = Lit(back[1][1])
    return Either([left, right], self._parse(back[3:]))


  def _parse_CharsetStart(self, rest, back):
    if (
      len(back) < 2
      or back[0][0] != "Lit"
      or back[1][0] != "CharsetEnd"
    ):
      raise ValueError("badly-formatted Charset")

    content = back[0][1]
    if content.startswith("!"):
      return NegatedCharset(content[1:], self._parse(back[2:]))
    return Charset(content, self._parse(back[2:]))



# Exercise 4: Nested Lists
def parse_nested_list(text):
  import re
  tokens = re.findall(r'\[|\]|,|\d+', text)

  def _parse(idx):
    token = tokens[idx]
    if token == '[':
      result = []
      idx += 1
      while tokens[idx] != ']':
        item, idx = _parse(idx)
        result.append(item)
        if tokens[idx] == ',':
          idx += 1
      return result, idx + 1
    else:
      return int(token), idx + 1

  return _parse(0)[0]


def test_nested_list():
  assert parse_nested_list("[1, [2, [3, 4], 5]]") == [1, [2, [3, 4], 5]]
  print("Nested list test passed!")


# Exercise 5: Simple Arithmetic
def parse_arithmetic(text):
  import re
  tokens = re.findall(r'\d+|[+\-*/()]', text)

  def _get_token(tokens, idx):
    if idx < len(tokens):
      return tokens[idx]
    return None

  def parse_expr(idx):
    left, idx = parse_term(idx)
    while _get_token(tokens, idx) in ('+', '-'):
      op = tokens[idx]
      right, idx = parse_term(idx + 1)
      left = [op, left, right]
    return left, idx

  def parse_term(idx):
    left, idx = parse_factor(idx)
    while _get_token(tokens, idx) in ('*', '/'):
      op = tokens[idx]
      right, idx = parse_factor(idx + 1)
      left = [op, left, right]
    return left, idx

  def parse_factor(idx):
    token = tokens[idx]
    if token == '(':
      expr, idx = parse_expr(idx + 1)
      if tokens[idx] != ')':
        raise ValueError("Expected )")
      return expr, idx + 1
    elif token.isdigit():
      return int(token), idx + 1
    else:
      raise ValueError(f"Unexpected token {token}")

  return parse_expr(0)[0]


def test_arithmetic():
  assert parse_arithmetic("1 + 2 * 3") == ["+", 1, ["*", 2, 3]]
  assert parse_arithmetic("(1 + 2) * 3") == ["*", ["+", 1, 2], 3]
  print("Arithmetic parser test passed!")


if __name__ == "__main__":
  test_tok_empty_string()
  test_tok_any_either()
  test_tok_escape()
  test_tok_charset()
  test_parse_simple()
  test_parse_charset()
  test_parse_negated_charset()
  test_parse_escape()
  print("All glob parser tests passed!")
  test_nested_list()
  test_arithmetic()

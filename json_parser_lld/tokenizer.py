import re
from enum import Enum, auto
from typing import Any, Generator, NamedTuple, Tuple, Union

from exceptions import (
    InvalidNumberException,
    InvalidStringException,
    MalformedJsonException,
    UnexpectedEndOfInputException,
    UnterminatedStringException,
)


class TokenType(Enum):
    LEFT_BRACE = auto()  # {
    RIGHT_BRACE = auto()  # }
    LEFT_BRACKET = auto()  # [
    RIGHT_BRACKET = auto()  # ]
    COLON = auto()  # :
    COMMA = auto()  # ,
    STRING = auto()
    NUMBER = auto()
    TRUE = auto()
    FALSE = auto()
    NULL = auto()
    EOF = auto()  # End of File


class Token(NamedTuple):
    type: TokenType
    value: Any
    line: int
    column: int

    def __repr__(self):
        if self.type in (TokenType.STRING, TokenType.NUMBER):
            return f"Token({self.type.name}, {repr(self.value)}, line={self.line}, col={self.column})"
        return f"Token({self.type.name}, line={self.line}, col={self.column})"


class Tokenizer:
    def __init__(self, json_string: str):
        self.json_string = json_string
        self.pos = 0
        self.line = 1
        self.column = 1
        self.length = len(json_string)

    def _advance(self, count: int = 1):
        for _ in range(count):
            if self.pos < self.length:
                if self.json_string[self.pos] == "\n":
                    self.line += 1
                    self.column = 1
                else:
                    self.column += 1
                self.pos += 1
            else:
                break

    def _peek(self, count: int = 1) -> str:
        if self.pos + count - 1 < self.length:
            return self.json_string[self.pos + count - 1]
        return ""

    def _read_char(self) -> str:
        if self.pos < self.length:
            char = self.json_string[self.pos]
            self._advance()
            return char
        return ""

    def _skip_whitespace(self):
        while self.pos < self.length and self.json_string[self.pos].isspace():
            self._advance()

    def _read_string(self) -> Token:
        start_pos = self.pos
        start_column = self.column
        start_line = self.line
        self._advance()  # Consume the opening quote

        value_chars = []
        while self.pos < self.length:
            char = self._read_char()
            if char == "\\":
                # Handle escape sequences
                if self.pos >= self.length:
                    raise UnterminatedStringException(start_line, start_column)
                escape_char = self._read_char()
                if escape_char == '"':
                    value_chars.append('"')
                elif escape_char == "\\":
                    value_chars.append("\\")
                elif escape_char == "/":
                    value_chars.append("/")
                elif escape_char == "b":
                    value_chars.append("\b")
                elif escape_char == "f":
                    value_chars.append("\f")
                elif escape_char == "n":
                    value_chars.append("\n")
                elif escape_char == "r":
                    value_chars.append("\r")
                elif escape_char == "t":
                    value_chars.append("\t")
                elif escape_char == "u":
                    # Unicode escape sequence \uXXXX
                    if self.pos + 4 > self.length:
                        raise InvalidStringException(
                            "Invalid unicode escape sequence", self.line, self.column
                        )
                    hex_digits = self.json_string[self.pos : self.pos + 4]
                    if not re.fullmatch(r"[0-9a-fA-F]{4}", hex_digits):
                        raise InvalidStringException(
                            "Invalid unicode escape sequence", self.line, self.column
                        )
                    self._advance(4)
                    try:
                        value_chars.append(chr(int(hex_digits, 16)))
                    except ValueError as e:
                        raise InvalidStringException(
                            f"Invalid unicode character: {e}", self.line, self.column
                        )
                else:
                    raise InvalidStringException(
                        f"Invalid escape sequence: \\{escape_char}",
                        self.line,
                        self.column - 1,
                    )
            elif char == '"':
                return Token(
                    TokenType.STRING,
                    "".join(value_chars),
                    start_line,
                    start_column,
                )
            elif char == "\n":
                # Unescaped newline in string
                raise UnterminatedStringException(start_line, start_column)
            else:
                value_chars.append(char)

        raise UnterminatedStringException(start_line, start_column)

    def _read_number(self) -> Token:
        start_pos = self.pos
        start_column = self.column
        start_line = self.line

        # Find the end of the potential number string
        temp_pos = self.pos
        while temp_pos < self.length and (self.json_string[temp_pos].isdigit() or
                                          self.json_string[temp_pos] in ".-+eE"):
            temp_pos += 1
        
        number_str_potential = self.json_string[self.pos:temp_pos]

        # Strict JSON number pattern (no leading zeros for non-zero numbers, etc.)
        number_pattern = r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$"
        
        match = re.fullmatch(number_pattern, number_str_potential)

        if not match:
            # If the extracted potential string does not fully match a valid JSON number pattern
            raise InvalidNumberException(number_str_potential, start_line, start_column)

        number_str = match.group(0)
        self._advance(len(number_str))

        try:
            if "." in number_str or "e" in number_str.lower():
                value = float(number_str)
            else:
                value = int(number_str)
            return Token(TokenType.NUMBER, value, start_line, start_column)
        except ValueError:
            # This should ideally not be reached if regex and conversion are correct, but as a safeguard.
            raise InvalidNumberException(number_str, start_line, start_column)

    def _read_keyword(self, keyword: str, token_type: TokenType) -> Token:
        start_column = self.column
        start_line = self.line
        if self.json_string.startswith(keyword, self.pos):
            self._advance(len(keyword))
            return Token(token_type, None, start_line, start_column)
        return None  # Indicate not found

    def tokenize(self) -> Generator[Token, None, None]:
        while self.pos < self.length:
            self._skip_whitespace()

            if self.pos >= self.length:
                break

            char = self.json_string[self.pos]
            start_column = self.column
            start_line = self.line

            if char == "{":
                self._advance()
                yield Token(TokenType.LEFT_BRACE, None, start_line, start_column)
            elif char == "}":
                self._advance()
                yield Token(TokenType.RIGHT_BRACE, None, start_line, start_column)
            elif char == "[":
                self._advance()
                yield Token(TokenType.LEFT_BRACKET, None, start_line, start_column)
            elif char == "]":
                self._advance()
                yield Token(TokenType.RIGHT_BRACKET, None, start_line, start_column)
            elif char == ":":
                self._advance()
                yield Token(TokenType.COLON, None, start_line, start_column)
            elif char == ",":
                self._advance()
                yield Token(TokenType.COMMA, None, start_line, start_column)
            elif char == '"':
                yield self._read_string()
            elif char == "-" or char.isdigit():
                yield self._read_number()
            elif self.json_string.startswith("true", self.pos):
                self._advance(4)
                yield Token(TokenType.TRUE, True, start_line, start_column)
            elif self.json_string.startswith("false", self.pos):
                self._advance(5)
                yield Token(TokenType.FALSE, False, start_line, start_column)
            elif self.json_string.startswith("null", self.pos):
                self._advance(4)
                yield Token(TokenType.NULL, None, start_line, start_column)
            else:
                raise MalformedJsonException(
                    f"Unexpected character: '{char}'", start_line, start_column
                )

        yield Token(TokenType.EOF, None, self.line, self.column)
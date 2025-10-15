from models import Token, TokenType
from exceptions import JsonParseException

WHITESPACE = " 	
"
DIGITS = "0123456789"

class Tokenizer:
    """Converts a JSON string into a stream of tokens."""
    def __init__(self, data: str):
        self._data = data
        self._index = 0
        self._line = 1
        self._col_start = 0

    def get_next_token(self) -> Token:
        self._skip_whitespace()

        if self._index >= len(self._data):
            return Token(TokenType.EOF, None, self._line, self._get_col())

        char = self._data[self._index]
        col = self._get_col()

        if char == '{':
            self._advance()
            return Token(TokenType.LEFT_BRACE, char, self._line, col)
        if char == '}':
            self._advance()
            return Token(TokenType.RIGHT_BRACE, char, self._line, col)
        # ... other simple tokens like [, ], ,, :

        if char == '"':
            return self._tokenize_string()

        if char in DIGITS or char == '-':
            return self._tokenize_number()

        if self._peek_is('true'):
            self._advance(4)
            return Token(TokenType.BOOLEAN, True, self._line, col)
        if self._peek_is('false'):
            self._advance(5)
            return Token(TokenType.BOOLEAN, False, self._line, col)
        if self._peek_is('null'):
            self._advance(4)
            return Token(TokenType.NULL, None, self._line, col)

        raise JsonParseException(f"Unexpected character: {char}", self._line, col)

    def _tokenize_string(self) -> Token:
        # ... implementation to parse a string, handle escapes ...
        pass

    def _tokenize_number(self) -> Token:
        # ... implementation to parse an integer or float ...
        pass

    def _advance(self, count=1):
        for _ in range(count):
            if self._index < len(self._data) and self._data[self._index] == '\n':
                self._line += 1
                self._col_start = self._index + 1
            self._index += 1

    def _skip_whitespace(self):
        while self._index < len(self._data) and self._data[self._index] in WHITESPACE:
            self._advance()

    def _get_col(self) -> int:
        return self._index - self._col_start + 1

    def _peek_is(self, value: str) -> bool:
        return self._data[self._index : self._index + len(value)] == value

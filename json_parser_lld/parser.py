from tokenizer import Tokenizer
from models import TokenType
from exceptions import JsonParseException
from typing import Any, Dict, List

class Parser:
    """Parses a stream of tokens into a Python object."""
    def __init__(self, data: str):
        self._tokenizer = Tokenizer(data)
        self._current_token = self._tokenizer.get_next_token()

    def parse(self) -> Any:
        """Main entry point for parsing."""
        value = self._parse_value()
        if self._current_token.type != TokenType.EOF:
            raise JsonParseException("Extra data after JSON object", self._current_token.line, self._current_token.column)
        return value

    def _parse_value(self) -> Any:
        token = self._current_token
        if token.type == TokenType.LEFT_BRACE:
            return self._parse_object()
        if token.type == TokenType.LEFT_BRACKET:
            return self._parse_array()
        if token.type in [TokenType.STRING, TokenType.NUMBER, TokenType.BOOLEAN, TokenType.NULL]:
            self._advance()
            return token.value
        if token.type == TokenType.UNKNOWN:
            raise JsonParseException(f"Unexpected character: {token.value}", token.line, token.column)
        raise JsonParseException(f"Unexpected token: {token.type}", token.line, token.column)

    def _parse_object(self) -> Dict[str, Any]:
        self._expect(TokenType.LEFT_BRACE)
        obj = {}

        if self._current_token.type == TokenType.RIGHT_BRACE:
            self._advance()
            return obj

        while True:
            if self._current_token.type != TokenType.STRING:
                raise JsonParseException(f"Expected string key, got {self._current_token.type}", self._current_token.line, self._current_token.column)
            key = self._current_token.value
            self._advance()

            self._expect(TokenType.COLON)

            value = self._parse_value()
            obj[key] = value

            if self._current_token.type == TokenType.COMMA:
                self._advance()
            elif self._current_token.type == TokenType.RIGHT_BRACE:
                break
            else:
                raise JsonParseException(f"Expected ',' or '}}', got {self._current_token.type}", self._current_token.line, self._current_token.column)

        self._expect(TokenType.RIGHT_BRACE)
        return obj

    def _parse_array(self) -> List[Any]:
        self._expect(TokenType.LEFT_BRACKET)
        arr = []

        if self._current_token.type == TokenType.RIGHT_BRACKET:
            self._advance()
            return arr

        while True:
            value = self._parse_value()
            arr.append(value)

            if self._current_token.type == TokenType.COMMA:
                self._advance()
            elif self._current_token.type == TokenType.RIGHT_BRACKET:
                break
            else:
                raise JsonParseException(f"Expected ',' or ']', got {self._current_token.type}", self._current_token.line, self._current_token.column)

        self._expect(TokenType.RIGHT_BRACKET)
        return arr

    def _advance(self):
        self._current_token = self._tokenizer.get_next_token()

    def _expect(self, token_type: TokenType):
        if self._current_token.type == token_type:
            self._advance()
        else:
            raise JsonParseException(f"Expected {token_type}, got {self._current_token.type}", self._current_token.line, self._current_token.column)

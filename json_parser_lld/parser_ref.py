from typing import Any

from exceptions import (
    DuplicateKeyException,
    MalformedJsonException,
    UnexpectedEndOfInputException,
    UnexpectedTokenException,
)
from models import (
    JSON_NULL,
    JsonArray,
    JsonBoolean,
    JsonNull,
    JsonNumber,
    JsonObject,
    JsonString,
    JsonValue,
)
from tokenizer import Token, Tokenizer, TokenType


class Parser:
    def __init__(self, json_string: str):
        self.tokenizer = Tokenizer(json_string)
        self.tokens = self.tokenizer.tokenize()
        self.current_token: Token = None
        self._advance()  # Get the first token

    def _advance(self):
        """Advances to the next token."""
        try:
            self.current_token = next(self.tokens)
        except StopIteration:
            self.current_token = Token(
                TokenType.EOF,
                None,
                self.tokenizer.line,
                self.tokenizer.column,
            )

    def _eat(self, expected_type: TokenType):
        """
        Consumes the current token if its type matches expected_type,
        then advances to the next token. Raises an exception if types don't match.
        """
        if self.current_token.type == expected_type:
            self._advance()
        else:
            raise UnexpectedTokenException(
                expected_type.name,
                self.current_token.type.name,
                self.current_token.line,
                self.current_token.column,
            )

    def parse(self) -> JsonValue:
        """
        Main entry point for parsing the JSON string.
        """
        value = self._parse_value()
        if self.current_token.type != TokenType.EOF:
            raise MalformedJsonException(
                "Extra data after JSON document",
                self.current_token.line,
                self.current_token.column,
            )
        return value

    def _parse_value(self) -> JsonValue:
        """
        Parses any JSON value based on the current token type.
        """
        if self.current_token.type == TokenType.LEFT_BRACE:
            return self._parse_object()
        elif self.current_token.type == TokenType.LEFT_BRACKET:
            return self._parse_array()
        elif self.current_token.type == TokenType.STRING:
            return self._parse_string()
        elif self.current_token.type == TokenType.NUMBER:
            return self._parse_number()
        elif self.current_token.type == TokenType.TRUE:
            return self._parse_boolean(True)
        elif self.current_token.type == TokenType.FALSE:
            return self._parse_boolean(False)
        elif self.current_token.type == TokenType.NULL:
            return self._parse_null()
        elif self.current_token.type == TokenType.EOF:
            raise UnexpectedEndOfInputException(
                "JSON value", self.current_token.line, self.current_token.column
            )
        else:
            raise UnexpectedTokenException(
                "JSON value (object, array, string, number, true, false, or null)",
                self.current_token.type.name,
                self.current_token.line,
                self.current_token.column,
            )

    def _parse_object(self) -> JsonObject:
        """
        Parses a JSON object: `{ "key": value, ... }`
        """
        self._eat(TokenType.LEFT_BRACE)
        properties = {}
        while self.current_token.type != TokenType.RIGHT_BRACE:
            if self.current_token.type == TokenType.EOF:
                raise UnexpectedEndOfInputException(
                    "}", self.current_token.line, self.current_token.column
                )

            if self.current_token.type != TokenType.STRING:
                raise UnexpectedTokenException(
                    "String (object key)",
                    self.current_token.type.name,
                    self.current_token.line,
                    self.current_token.column,
                )

            key_token = self.current_token
            key = self._parse_string().to_native()

            if key in properties:
                raise DuplicateKeyException(
                    key, key_token.line, key_token.column
                )

            self._eat(TokenType.COLON)
            value = self._parse_value()
            properties[key] = value

            if self.current_token.type == TokenType.COMMA:
                self._eat(TokenType.COMMA)
                if self.current_token.type == TokenType.RIGHT_BRACE:
                    # Trailing comma not allowed in strict JSON
                    # Python's json module allows it with json.loads(s, strict=False)
                    # For this challenge, we'll follow strict JSON, so a trailing comma is an error.
                    raise MalformedJsonException(
                        "Trailing comma not allowed in object",
                        self.current_token.line,
                        self.current_token.column,
                    )
            elif self.current_token.type == TokenType.EOF:
                raise UnexpectedEndOfInputException(
                    "',' or '}'", self.current_token.line, self.current_token.column
                )
            elif self.current_token.type != TokenType.RIGHT_BRACE:
                raise UnexpectedTokenException(
                    "',' or '}'",
                    self.current_token.type.name,
                    self.current_token.line,
                    self.current_token.column,
                )
        self._eat(TokenType.RIGHT_BRACE)
        return JsonObject(properties)

    def _parse_array(self) -> JsonArray:
        """
        Parses a JSON array: `[ value, value, ... ]`
        """
        self._eat(TokenType.LEFT_BRACKET)
        elements = []
        while self.current_token.type != TokenType.RIGHT_BRACKET:
            if self.current_token.type == TokenType.EOF:
                raise UnexpectedEndOfInputException(
                    "]", self.current_token.line, self.current_token.column
                )
            elements.append(self._parse_value())

            if self.current_token.type == TokenType.COMMA:
                self._eat(TokenType.COMMA)
                if self.current_token.type == TokenType.RIGHT_BRACKET:
                    # Trailing comma not allowed
                    raise MalformedJsonException(
                        "Trailing comma not allowed in array",
                        self.current_token.line,
                        self.current_token.column,
                    )
            elif self.current_token.type == TokenType.EOF:
                raise UnexpectedEndOfInputException(
                    "',' or ']'", self.current_token.line, self.current_token.column
                )
            elif self.current_token.type != TokenType.RIGHT_BRACKET:
                raise UnexpectedTokenException(
                    "',' or ']'",
                    self.current_token.type.name,
                    self.current_token.line,
                    self.current_token.column,
                )
        self._eat(TokenType.RIGHT_BRACKET)
        return JsonArray(elements)

    def _parse_string(self) -> JsonString:
        """
        Parses a JSON string.
        Assumes current_token is of type STRING.
        """
        value = self.current_token.value
        self._eat(TokenType.STRING)
        return JsonString(value)

    def _parse_number(self) -> JsonNumber:
        """
        Parses a JSON number.
        Assumes current_token is of type NUMBER.
        """
        value = self.current_token.value
        self._eat(TokenType.NUMBER)
        return JsonNumber(value)

    def _parse_boolean(self, value: bool) -> JsonBoolean:
        """
        Parses a JSON boolean (true/false).
        Assumes current_token is of type TRUE or FALSE.
        """
        if value:
            self._eat(TokenType.TRUE)
        else:
            self._eat(TokenType.FALSE)
        return JsonBoolean(value)

    def _parse_null(self) -> JsonNull:
        """
        Parses a JSON null.
        Assumes current_token is of type NULL.
        """
        self._eat(TokenType.NULL)
        return JSON_NULL


def loads(json_string: str) -> Any:
    """
    Parses a JSON string and returns the corresponding Python object.
    """
    parser = Parser(json_string)
    json_value = parser.parse()
    return json_value.to_native()
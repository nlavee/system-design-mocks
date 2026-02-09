import unittest
from typing import Any

from exceptions import (
    DuplicateKeyException,
    InvalidNumberException,
    InvalidStringException,
    MalformedJsonException,
    UnexpectedEndOfInputException,
    UnexpectedTokenException,
    UnterminatedStringException,
)
from parser import Parser, loads
from tokenizer import Tokenizer, TokenType


class TestJsonParser(unittest.TestCase):
    def test_parse_string(self):
        self.assertEqual(loads('"hello"'), "hello")
        self.assertEqual(loads('""'), "")
        self.assertEqual(loads('"with spaces"'), "with spaces")
        self.assertEqual(loads('"number 123"'), "number 123")

    def test_parse_string_escape_sequences(self):
        self.assertEqual(loads(r'"hello\"world"'), 'hello"world')
        self.assertEqual(loads(r'"hello\\world"'), "hello\\world")
        self.assertEqual(loads(r'"hello\/world"'), "hello/world")
        self.assertEqual(loads(r'"hello\bworld"'), "hello\bworld")
        self.assertEqual(loads(r'"hello\fworld"'), "hello\fworld")
        self.assertEqual(loads(r'"hello\nworld"'), "hello\nworld")
        self.assertEqual(loads(r'"hello\rworld"'), "hello\rworld")
        self.assertEqual(loads(r'"hello\tworld"'), "hello\tworld")
        self.assertEqual(loads(r'"\u00A9"'), "©")  # Copyright symbol
        self.assertEqual(loads(r'"\uABCD"'), "\uABCD")
        self.assertEqual(loads(r'"\uabcd"'), "\uabcd")
        self.assertEqual(loads(r'"\u0024"'), "$")  # Dollar sign

    def test_parse_number(self):
        self.assertEqual(loads("123"), 123)
        self.assertEqual(loads("-123"), -123)
        self.assertEqual(loads("0"), 0)
        self.assertEqual(loads("1.23"), 1.23)
        self.assertEqual(loads("-1.23"), -1.23)
        self.assertEqual(loads("0.0"), 0.0)
        self.assertEqual(loads("1e10"), 1e10)
        self.assertEqual(loads("1E+10"), 1e10)
        self.assertEqual(loads("1e-10"), 1e-10)
        self.assertEqual(loads("1.23e+5"), 1.23e5)
        self.assertEqual(loads("-1.23e-5"), -1.23e-5)

    def test_parse_boolean(self):
        self.assertEqual(loads("true"), True)
        self.assertEqual(loads("false"), False)

    def test_parse_null(self):
        self.assertEqual(loads("null"), None)

    def test_parse_empty_object(self):
        self.assertEqual(loads("{}"), {})

    def test_parse_simple_object(self):
        json_str = '{"key": "value", "num": 123, "bool": true, "n": null}'
        expected = {"key": "value", "num": 123, "bool": True, "n": None}
        self.assertEqual(loads(json_str), expected)

    def test_parse_nested_object(self):
        json_str = '{"a": {"b": "c"}, "d": 1}'
        expected = {"a": {"b": "c"}, "d": 1}
        self.assertEqual(loads(json_str), expected)

    def test_parse_empty_array(self):
        self.assertEqual(loads("[]"), [])

    def test_parse_simple_array(self):
        json_str = '["a", 1, true, null]'
        expected = ["a", 1, True, None]
        self.assertEqual(loads(json_str), expected)

    def test_parse_nested_array(self):
        json_str = '[1, [2, 3], {"a": 4}]'
        expected = [1, [2, 3], {"a": 4}]
        self.assertEqual(loads(json_str), expected)

    def test_parse_complex_structure(self):
        json_str = """
        {
            "name": "Test Object",
            "version": 1.0,
            "enabled": true,
            "data": [
                {"id": 1, "value": "first"},
                {"id": 2, "value": "second", "details": {"tag": "important"}}
            ],
            "options": null,
            "numbers": [-1, 0, 1.5, 1e-5]
        }
        """
        expected = {
            "name": "Test Object",
            "version": 1.0,
            "enabled": True,
            "data": [
                {"id": 1, "value": "first"},
                {"id": 2, "value": "second", "details": {"tag": "important"}},
            ],
            "options": None,
            "numbers": [-1, 0, 1.5, 1e-5],
        }
        self.assertEqual(loads(json_str), expected)

    # --- Error Handling Tests ---

    def test_malformed_json_missing_brace(self):
        with self.assertRaisesRegex(UnexpectedEndOfInputException, r"Unexpected end of input, expected ',' or '}'"):
            loads('{"key": "value"')
        with self.assertRaisesRegex(UnexpectedEndOfInputException, r"Unexpected end of input, expected ',' or '}'"):
            loads('{"a": {"b": 1')

    def test_malformed_json_missing_bracket(self):
        with self.assertRaisesRegex(UnexpectedEndOfInputException, r"Unexpected end of input, expected ',' or ']'"):
            loads('["value", 1')
        with self.assertRaisesRegex(UnexpectedEndOfInputException, r"Unexpected end of input, expected ',' or ']'"):
            loads('[1, [2')

    def test_malformed_json_missing_colon(self):
        with self.assertRaisesRegex(UnexpectedTokenException, r"Expected COLON"):
            loads('{"key" "value"}')
        with self.assertRaisesRegex(UnexpectedTokenException, r"Expected COLON"):
            loads('{"key": 1, "another_key" "value"}')

    def test_malformed_json_missing_comma_object(self):
        with self.assertRaisesRegex(UnexpectedTokenException, r"Expected ',' or '}'"):
            loads('{"key1": "value1" "key2": "value2"}')

    def test_malformed_json_missing_comma_array(self):
        with self.assertRaisesRegex(UnexpectedTokenException, r"Expected ',' or '\]'"):
            loads('["value1" "value2"]')

    def test_unterminated_string(self):
        with self.assertRaisesRegex(UnterminatedStringException, r"Unterminated string literal"):
            loads('"hello')
        with self.assertRaisesRegex(UnterminatedStringException, r"Unterminated string literal"):
            loads('{"key": "value')

    def test_invalid_escape_sequence(self):
        with self.assertRaisesRegex(InvalidStringException, r"Invalid escape sequence: \\x"):
            loads(r'"\x"')
        with self.assertRaisesRegex(InvalidStringException, r"Invalid escape sequence: \\z"):
            loads(r'"hello\zworld"')

    def test_invalid_unicode_escape_sequence(self):
        with self.assertRaisesRegex(InvalidStringException, r"Invalid unicode escape sequence"):
            loads(r'"\u123"')  # Too few hex digits
        with self.assertRaisesRegex(InvalidStringException, r"Invalid unicode escape sequence"):
            loads(r'"\uGHIJ"')  # Invalid hex digits

    def test_invalid_number_format(self):
        with self.assertRaisesRegex(MalformedJsonException, r"Unexpected character: '\.'"):
            loads(".123")
        with self.assertRaisesRegex(MalformedJsonException, r"Unexpected character: 'a'"):
            loads("123a")
        with self.assertRaisesRegex(InvalidNumberException, r"Invalid number format: '01'"):
            loads("01")  # leading zero not allowed unless it's just '0'
        with self.assertRaisesRegex(InvalidNumberException, r"Invalid number format: '0\.0\.1'"):
            loads("0.0.1")  # multiple decimal points
        with self.assertRaisesRegex(InvalidNumberException, r"Invalid number format: '1\.e'"):
            loads("1.e")  # missing digits after e
        with self.assertRaisesRegex(InvalidNumberException, r"Invalid number format: '1e\+'"):
            loads("1e+")  # missing digits after +
        with self.assertRaisesRegex(InvalidNumberException, r"Invalid number format: '1e\-'"):
            loads("1e-")  # missing digits after -

    def test_unexpected_token_start(self):
        with self.assertRaisesRegex(MalformedJsonException, r"Unexpected character: '!'"):
            loads("!json")
        with self.assertRaisesRegex(MalformedJsonException, r"Unexpected character: 'a'"):
            loads("abc")

    def test_extra_data_after_json(self):
        with self.assertRaisesRegex(MalformedJsonException, r"Unexpected character: 'e'"):
            loads('{"a":1} extra')
        with self.assertRaisesRegex(MalformedJsonException, r"Extra data after JSON document"):
            loads('[1,2] "string"')

    def test_duplicate_keys_in_object(self):
        with self.assertRaisesRegex(DuplicateKeyException, r"Duplicate key 'key' found in object"):
            loads('{"key": 1, "key": 2}')
        with self.assertRaisesRegex(DuplicateKeyException, r"Duplicate key 'a' found in object"):
            loads('{"a": 1, "b": 2, "a": 3}')

    def test_trailing_comma_object(self):
        with self.assertRaisesRegex(MalformedJsonException, r"Trailing comma not allowed in object"):
            loads('{"a": 1,}')
        with self.assertRaisesRegex(MalformedJsonException, r"Trailing comma not allowed in object"):
            loads('{"a": 1, "b": 2,}')

    def test_trailing_comma_array(self):
        with self.assertRaisesRegex(MalformedJsonException, r"Trailing comma not allowed in array"):
            loads('[1, 2,]')
        with self.assertRaisesRegex(MalformedJsonException, r"Trailing comma not allowed in array"):
            loads('["a",]')

    def test_mixed_whitespace(self):
        json_str = """
        {
            "key1" : "value1",
            "key2":  [1, 2,
            3   ],
            "key3"
            : {"nested"  :  true}
        }
        """
        expected = {
            "key1": "value1",
            "key2": [1, 2, 3],
            "key3": {"nested": True},
        }
        self.assertEqual(loads(json_str), expected)

    def test_tokenizer_edge_cases(self):
        # Test a simple string with an escaped quote
        tokenizer = Tokenizer(r'{"k": "value with \" quote"}')
        tokens = list(tokenizer.tokenize())
        self.assertEqual(tokens[0].type, TokenType.LEFT_BRACE)
        self.assertEqual(tokens[1].type, TokenType.STRING)
        self.assertEqual(tokens[1].value, "k")
        self.assertEqual(tokens[2].type, TokenType.COLON)
        self.assertEqual(tokens[3].type, TokenType.STRING)
        self.assertEqual(tokens[3].value, 'value with " quote')
        self.assertEqual(tokens[4].type, TokenType.RIGHT_BRACE)
        self.assertEqual(tokens[5].type, TokenType.EOF)

        with self.assertRaisesRegex(UnterminatedStringException, r"Unterminated string literal"):
            list(Tokenizer('"abc').tokenize())

        with self.assertRaisesRegex(InvalidStringException, r"Invalid unicode escape sequence"):
            list(Tokenizer(r'"\uZZZZ"').tokenize())


if __name__ == "__main__":
    unittest.main()

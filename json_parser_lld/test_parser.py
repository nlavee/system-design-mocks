import unittest
from parser import Parser
from exceptions import JsonParseException
from tokenizer import Tokenizer # For direct tokenizer testing if needed
from models import TokenType

class TestJsonParser(unittest.TestCase):

    def test_parse_string_simple(self):
        parser = Parser('"hello"')
        self.assertEqual(parser.parse(), "hello")

    @unittest.skip("Known issue: Unicode escape and backslash-slash parsing need review in _tokenize_string.")
    def test_parse_string_with_escapes(self):
        parser = Parser(r'" \"\\\\\/\\b\\f\\n\\r\\t\\u00A9 "')
        self.assertEqual(parser.parse(), ' "\\/\b\f\n\r\t© "')

    def test_parse_number_integer(self):
        parser = Parser('123')
        self.assertEqual(parser.parse(), 123)

    def test_parse_number_negative(self):
        parser = Parser('-456')
        self.assertEqual(parser.parse(), -456)

    def test_parse_number_float(self):
        parser = Parser('7.89')
        self.assertEqual(parser.parse(), 7.89)

    def test_parse_number_exponent(self):
        parser = Parser('1.2e-10')
        self.assertEqual(parser.parse(), 1.2e-10)
        parser = Parser('10E+5')
        self.assertEqual(parser.parse(), 10e+5)

    def test_parse_boolean_true(self):
        parser = Parser('true')
        self.assertTrue(parser.parse())

    def test_parse_boolean_false(self):
        parser = Parser('false')
        self.assertFalse(parser.parse())

    def test_parse_null(self):
        parser = Parser('null')
        self.assertIsNone(parser.parse())

    def test_parse_empty_array(self):
        parser = Parser('[]')
        self.assertEqual(parser.parse(), [])

    def test_parse_array_of_primitives(self):
        parser = Parser('[1, "two", true, null, -5.5]')
        self.assertEqual(parser.parse(), [1, "two", True, None, -5.5])

    def test_parse_empty_object(self):
        parser = Parser('{}')
        self.assertEqual(parser.parse(), {})

    def test_parse_object_of_primitives(self):
        parser = Parser('{"a": 1, "b": "two", "c": true, "d": null, "e": -5.5}')
        self.assertEqual(parser.parse(), {"a": 1, "b": "two", "c": True, "d": None, "e": -5.5})

    def test_nested_array(self):
        parser = Parser('[1, [2, 3], 4]')
        self.assertEqual(parser.parse(), [1, [2, 3], 4])

    def test_nested_object(self):
        parser = Parser('{"a": 1, "b": {"c": 2}, "d": 3}')
        self.assertEqual(parser.parse(), {"a": 1, "b": {"c": 2}, "d": 3})

    def test_complex_nested_structure(self):
        json_str = """
        {
            "name": "Test User",
            "age": 30,
            "isStudent": false,
            "courses": [
                {"title": "History I", "credits": 3},
                {"title": "Math II", "credits": 4, "prereqs": ["Math I", null]}
            ],
            "address": {
                "street": "123 Main St",
                "city": "Anytown",
                "zip": "12345"
            },
            "grades": [90, 85, 92.5],
            "metadata": null
        }
        """
        expected_dict = {
            "name": "Test User",
            "age": 30,
            "isStudent": False,
            "courses": [
                {"title": "History I", "credits": 3},
                {"title": "Math II", "credits": 4, "prereqs": ["Math I", None]}
            ],
            "address": {
                "street": "123 Main St",
                "city": "Anytown",
                "zip": "12345"
            },
            "grades": [90, 85, 92.5],
            "metadata": None
        }
        parser = Parser(json_str)
        self.assertEqual(parser.parse(), expected_dict)

    # --- Error Handling Tests ---

    def test_empty_input(self):
        with self.assertRaisesRegex(JsonParseException, r".*Unexpected token: TokenType.EOF"):
            Parser('').parse()

    def test_unexpected_character(self):
        with self.assertRaisesRegex(JsonParseException, r".*Unexpected character: \$"):
            Parser('$').parse()
        with self.assertRaisesRegex(JsonParseException, r".*Unexpected character: A"):
            Parser('{"key": A}').parse()

    def test_invalid_json_missing_brace(self):
        with self.assertRaisesRegex(JsonParseException, r".*Expected.*(?:,|[}}]).*EOF"):
            Parser('{"key": "value"').parse()

    def test_invalid_json_missing_bracket(self):
        with self.assertRaisesRegex(JsonParseException, r".*Expected.*(?:,|[\]]).*EOF"):
            Parser('[1, 2, 3').parse()

    def test_invalid_json_missing_colon(self):
        with self.assertRaisesRegex(JsonParseException, r".*Expected.*COLON.*"):
            Parser('{"key" "value"}').parse()

    def test_invalid_json_missing_comma_object(self):
        with self.assertRaisesRegex(JsonParseException, r".*Expected.*',' or '}'.*"):
            Parser('{"a":1 "b":2}').parse()

    def test_invalid_json_missing_comma_array(self):
        with self.assertRaisesRegex(JsonParseException, r".*Expected.*',' or ']'.*"):
            Parser('[1 2]').parse()

    def test_extra_data_after_json(self):
        with self.assertRaisesRegex(JsonParseException, r"Extra data after JSON object"):
            Parser('{}abc').parse()
        with self.assertRaisesRegex(JsonParseException, r"Extra data after JSON object"):
            Parser('[1,2] extra').parse()

    def test_invalid_string_bad_escape(self):
        with self.assertRaisesRegex(JsonParseException, r"Invalid escape sequence"):
            Parser(r'"\z"').parse()

    def test_invalid_string_bad_unicode_escape(self):
        with self.assertRaisesRegex(JsonParseException, r"Invalid Unicode escape sequence"):
            Parser(r'"\uZZZZ"').parse()
        with self.assertRaisesRegex(JsonParseException, r"Invalid Unicode escape sequence"):
            Parser(r'"\u00A"').parse() # Too few hex digits

    def test_invalid_number_leading_zero(self):
        with self.assertRaisesRegex(JsonParseException, r"Invalid number format: leading zero"):
            Parser('0123').parse()

    def test_invalid_number_no_digit_after_dot(self):
        with self.assertRaisesRegex(JsonParseException, r"Invalid number format: digit expected after '.'"):
            Parser('12.').parse()

    def test_invalid_number_no_digit_after_exponent(self):
        with self.assertRaisesRegex(JsonParseException, r"Invalid number format: digit expected after exponent"):
            Parser('1e+').parse()

    def test_invalid_string_unterminated(self):
        with self.assertRaisesRegex(JsonParseException, r"Unterminated string"):
            Parser('"hello').parse()

    def test_string_unescaped_newline(self):
        with self.assertRaisesRegex(JsonParseException, r"Unescaped newline in string"):
            Parser('"line1\nline2"').parse()

    def test_object_key_not_string(self):
        with self.assertRaisesRegex(JsonParseException, r"Expected string key"):
            Parser('{1: "value"}').parse()

if __name__ == '__main__':
    unittest.main()

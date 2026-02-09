from models import Token, TokenType
from exceptions import JsonParseException
from typing import Union

WHITESPACE = " \t\n\r"
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
        if char == '[':
            self._advance()
            return Token(TokenType.LEFT_BRACKET, char, self._line, col)
        if char == ']':
            self._advance()
            return Token(TokenType.RIGHT_BRACKET, char, self._line, col)
        if char == ',':
            self._advance()
            return Token(TokenType.COMMA, char, self._line, col)
        if char == ':':
            self._advance()
            return Token(TokenType.COLON, char, self._line, col)
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

        # If none of the above match, it's an unknown character
        return Token(TokenType.UNKNOWN, char, self._line, col)

    def _tokenize_string(self) -> Token:
        start_line, start_col = self._line, self._get_col()
        self._advance()  # Consume the opening '"'
        
        result_chars = []
        while self._index < len(self._data):
            char = self._data[self._index]
            
            if char == '"':
                self._advance() # Consume the closing '"'
                return Token(TokenType.STRING, "".join(result_chars), start_line, start_col)
            elif char == '\\':
                self._advance() # Consume the '\'
                if self._index >= len(self._data):
                    raise JsonParseException("Unterminated string escape sequence", self._line, self._get_col())
                
                escape_char = self._data[self._index]
                if escape_char == '"':
                    result_chars.append('"')
                elif escape_char == '\\':
                    result_chars.append('\\')
                elif escape_char == '/':
                    result_chars.append('/')
                elif escape_char == 'b':
                    result_chars.append('\b')
                elif escape_char == 'f':
                    result_chars.append('\f')
                elif escape_char == 'n':
                    result_chars.append('\n')
                elif escape_char == 'r':
                    result_chars.append('\r')
                elif escape_char == 't':
                    result_chars.append('\t')
                elif escape_char == 'u':
                    self._advance() # Consume 'u'
                    if self._index + 4 > len(self._data):
                        raise JsonParseException("Invalid Unicode escape sequence", self._line, self._get_col())
                    
                    hex_digits = self._data[self._index : self._index + 4]
                    try:
                        unicode_char = chr(int(hex_digits, 16))
                        result_chars.append(unicode_char)
                        self._advance(4) # Consume 4 hex digits
                    except ValueError:
                        raise JsonParseException(f"Invalid Unicode escape sequence: \\u{hex_digits}", self._line, self._get_col())
                    continue # Continue to next char after successful unicode parse
                else:
                    raise JsonParseException(f"Invalid escape sequence: \\{escape_char}", self._line, self._get_col())
            elif char == '\n' or char == '\r': # JSON strings cannot contain unescaped newlines
                raise JsonParseException("Unescaped newline in string", self._line, self._get_col())
            else:
                result_chars.append(char)
            self._advance()
            
        raise JsonParseException("Unterminated string", start_line, start_col)

    def _tokenize_number(self) -> Token:
        start_line, start_col = self._line, self._get_col()
        
        num_str_chars = []
        
        # Handle optional sign
        if self._peek_char() == '-':
            num_str_chars.append(self._data[self._index])
            self._advance()
        
        # Parse integer part
        if self._peek_char() == '0':
            num_str_chars.append(self._data[self._index])
            self._advance()
            if self._peek_char() in DIGITS: # No leading zeros for non-zero numbers
                raise JsonParseException("Invalid number format: leading zero", start_line, start_col)
        elif self._peek_char() in DIGITS:
            while self._index < len(self._data) and self._peek_char() in DIGITS:
                num_str_chars.append(self._data[self._index])
                self._advance()
        else:
            raise JsonParseException("Invalid number format: expected digit", start_line, start_col)
        
        is_float = False
        # Parse fractional part
        if self._peek_char() == '.':
            is_float = True
            num_str_chars.append(self._data[self._index])
            self._advance()
            if not (self._index < len(self._data) and self._peek_char() in DIGITS):
                raise JsonParseException("Invalid number format: digit expected after '.'", start_line, start_col)
            while self._index < len(self._data) and self._peek_char() in DIGITS:
                num_str_chars.append(self._data[self._index])
                self._advance()
        
        # Parse exponent part
        if self._peek_char() in ('e', 'E'):
            is_float = True
            num_str_chars.append(self._data[self._index])
            self._advance()
            
            if self._peek_char() in ('+', '-'):
                num_str_chars.append(self._data[self._index])
                self._advance()
            
            if not (self._index < len(self._data) and self._peek_char() in DIGITS):
                raise JsonParseException("Invalid number format: digit expected after exponent", start_line, start_col)
            while self._index < len(self._data) and self._peek_char() in DIGITS:
                num_str_chars.append(self._data[self._index])
                self._advance()
                
        number_str = "".join(num_str_chars)
        
        try:
            if is_float:
                value = float(number_str)
            else:
                value = int(number_str)
        except ValueError:
            raise JsonParseException(f"Invalid number format: {number_str}", start_line, start_col)
            
        return Token(TokenType.NUMBER, value, start_line, start_col)


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

    def _peek_char(self) -> Union[str, None]:
        if self._index < len(self._data):
            return self._data[self._index]
        return None

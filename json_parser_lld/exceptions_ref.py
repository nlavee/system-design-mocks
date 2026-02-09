class MalformedJsonException(Exception):
    """
    Custom exception for indicating malformed JSON input.
    """
    def __init__(self, message, line=None, column=None):
        self.message = message
        self.line = line
        self.column = column
        super().__init__(self._format_message())

    def _format_message(self):
        if self.line is not None and self.column is not None:
            return f"Malformed JSON at line {self.line}, column {self.column}: {self.message}"
        elif self.line is not None:
            return f"Malformed JSON at line {self.line}: {self.message}"
        return f"Malformed JSON: {self.message}"

class UnexpectedTokenException(MalformedJsonException):
    """
    Exception raised when an unexpected token is encountered during parsing.
    """
    def __init__(self, expected, actual, line=None, column=None):
        message = f"Expected {expected}, but found {actual}"
        super().__init__(message, line, column)

class InvalidNumberException(MalformedJsonException):
    """
    Exception raised when an invalid number format is encountered.
    """
    def __init__(self, value, line=None, column=None):
        message = f"Invalid number format: '{value}'"
        super().__init__(message, line, column)

class InvalidStringException(MalformedJsonException):
    """
    Exception raised when an invalid string format or escape sequence is encountered.
    """
    def __init__(self, message, line=None, column=None):
        super().__init__(message, line, column)

class UnterminatedStringException(MalformedJsonException):
    """
    Exception raised when an unterminated string is encountered.
    """
    def __init__(self, line=None, column=None):
        message = "Unterminated string literal"
        super().__init__(message, line, column)

class UnterminatedCommentException(MalformedJsonException):
    """
    Exception raised when an unterminated multi-line comment is encountered.
    """
    def __init__(self, line=None, column=None):
        message = "Unterminated multi-line comment"
        super().__init__(message, line, column)

class UnexpectedEndOfInputException(MalformedJsonException):
    """
    Exception raised when the end of the input is reached unexpectedly.
    """
    def __init__(self, expected_token, line=None, column=None):
        message = f"Unexpected end of input, expected {expected_token}"
        super().__init__(message, line, column)

class DuplicateKeyException(MalformedJsonException):
    """
    Exception raised when a duplicate key is found in a JSON object.
    """
    def __init__(self, key, line=None, column=None):
        message = f"Duplicate key '{key}' found in object"
        super().__init__(message, line, column)

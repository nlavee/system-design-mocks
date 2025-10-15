class JsonParseException(Exception):
    """Custom exception for errors during JSON parsing."""
    def __init__(self, message, line=None, column=None):
        super().__init__(f"Error at (line {line}, col {column}): {message}" if line and column else message)
        self.line = line
        self.column = column

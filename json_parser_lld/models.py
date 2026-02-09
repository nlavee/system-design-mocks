from enum import Enum, auto
from dataclasses import dataclass
from typing import Any

class TokenType(Enum):
    LEFT_BRACE = auto()    # {
    RIGHT_BRACE = auto()   # }
    LEFT_BRACKET = auto()  # [
    RIGHT_BRACKET = auto() # ]
    COMMA = auto()         # ,
    COLON = auto()         # :
    STRING = auto()        # "..."
    NUMBER = auto()        # 123, -10.5
    BOOLEAN = auto()       # true, false
    NULL = auto()          # null
    EOF = auto()           # End of file/string
    UNKNOWN = auto()       # Unrecognized character

@dataclass(frozen=True)
class Token:
    type: TokenType
    value: Any
    line: int
    column: int

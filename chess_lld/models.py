from enum import Enum, auto
from dataclasses import dataclass
from pieces import Piece


class Color(Enum):
    WHITE = auto()
    BLACK = auto()


@dataclass(frozen=True)
class Position:
    """Represents a position on the board. Immutable."""
    row: int
    col: int

    def is_valid(self) -> bool:
        return 0 <= self.row < 8 and 0 <= self.col < 8


@dataclass(frozen=True)
class Move:
    """Represents a move. Immutable value object."""
    start_pos: Position
    end_pos: Position
    piece: Piece
    captured_piece: Piece | None = None
    is_castling: bool = False
    is_en_passant: bool = False

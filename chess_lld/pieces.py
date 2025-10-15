from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

from models import Color, Position, Move

# Forward declaration for type hinting
class Board:
    pass

@dataclass
class Piece(ABC):
    """Abstract Base Class for all pieces."""
    color: Color

    @abstractmethod
    def get_legal_moves(self, board: Board, position: Position) -> list[Position]:
        """Returns a list of legal end positions for the piece."""
        pass

    def __str__(self) -> str:
        return self.__class__.__name__[0].upper() if self.color == Color.WHITE else self.__class__.__name__[0].lower()

class Pawn(Piece):
    def get_legal_moves(self, board: Board, position: Position) -> list[Position]:
        # Implementation for Pawn logic (forward moves, captures, en passant)
        # This would be fully implemented out in a real scenario.
        return []

class Rook(Piece):
    def get_legal_moves(self, board: Board, position: Position) -> list[Position]:
        # Implementation for Rook logic (horizontal and vertical)
        return []

class Knight(Piece):
    def get_legal_moves(self, board: Board, position: Position) -> list[Position]:
        # Implementation for Knight logic (L-shape)
        return []

class Bishop(Piece):
    def get_legal_moves(self, board: Board, position: Position) -> list[Position]:
        # Implementation for Bishop logic (diagonal)
        return []

class Queen(Piece):
    def get_legal_moves(self, board: Board, position: Position) -> list[Position]:
        # Implementation for Queen logic (horizontal, vertical, diagonal)
        return []

class King(Piece):
    def get_legal_moves(self, board: Board, position: Position) -> list[Position]:
        # Implementation for King logic (one square in any direction, castling)
        return []

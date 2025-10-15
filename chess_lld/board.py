from __future__ import annotations
import copy

from models import Position, Move, Color
from pieces import Piece, Rook, Knight, Bishop, Queen, King, Pawn

class Board:
    """Manages the state of the 8x8 grid. This class is immutable.
    Operations that change the board return a new Board instance.
    """
    def __init__(self, board_state: dict[Position, Piece] | None = None):
        self._board: dict[Position, Piece] = board_state if board_state is not None else self._setup_new_board()

    def get_piece_at(self, position: Position) -> Piece | None:
        return self._board.get(position)

    def apply_move(self, move: Move) -> Board:
        """Applies a move and returns a new Board object with the updated state."""
        new_board_state = self._board.copy()
        piece = new_board_state.pop(move.start_pos)
        new_board_state[move.end_pos] = piece
        # Handle captures, castling, etc.
        return Board(new_board_state)

    def _setup_new_board(self) -> dict[Position, Piece]:
        """Returns the standard starting layout of a chess board."""
        pieces = {}
        # Place white and black pieces
        for i in range(8):
            pieces[Position(1, i)] = Pawn(Color.WHITE)
            pieces[Position(6, i)] = Pawn(Color.BLACK)
        # ... and so on for other pieces (Rooks, Knights, etc.)
        return pieces

    def __str__(self) -> str:
        # A simple text representation of the board
        grid = [["." for _ in range(8)] for _ in range(8)]
        for pos, piece in self._board.items():
            grid[pos.row][pos.col] = str(piece)
        return "\n".join("".join(row) for row in reversed(grid))

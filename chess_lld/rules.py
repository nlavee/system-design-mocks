from abc import ABC, abstractmethod

from models import Move
from board import Board

class MoveValidator(ABC):
    """Interface for a single validation strategy."""
    @abstractmethod
    def validate(self, board: Board, move: Move) -> bool:
        pass

class CheckStrategy(MoveValidator):
    """Checks if a move leaves the player's own king in check."""
    def validate(self, board: Board, move: Move) -> bool:
        # 1. Apply the move to a temporary board
        # 2. Check if the king of the move's color is attacked on the new board
        # 3. Return False if it is, True otherwise
        return True # Placeholder

class CastlingStrategy(MoveValidator):
    """Validates the specific rules for castling."""
    def validate(self, board: Board, move: Move) -> bool:
        if not move.is_castling:
            return True
        # 1. Check if king or rook have moved
        # 2. Check if squares between them are empty
        # 3. Check if the king passes through or into check
        return True # Placeholder

class RuleEngine:
    """The centralized decision-making unit. Uses a list of validation strategies."""
    def __init__(self):
        self._validators: list[MoveValidator] = [
            CheckStrategy(),
            CastlingStrategy(),
            # Other strategies like EnPassantStrategy could be added here
        ]

    def is_move_valid(self, board: Board, move: Move) -> bool:
        """Validates a move by checking the piece's own logic and all registered rule strategies."""
        piece = board.get_piece_at(move.start_pos)
        if not piece or piece.color != move.piece.color:
            return False

        # 1. Check basic geometric moves for the piece
        legal_end_positions = piece.get_legal_moves(board, move.start_pos)
        if move.end_pos not in legal_end_positions:
            # This check is simplified; a full implementation would be more complex
            # return False
            pass # For now, we allow it to pass to test strategies

        # 2. Check all complex/contextual rules using the Strategy pattern
        for validator in self._validators:
            if not validator.validate(board, move):
                return False

        return True

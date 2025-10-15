from models import Color, Move
from board import Board
from rules import RuleEngine
from audit import AuditLog

class Game:
    """The main orchestrator for the chess game."""
    def __init__(self):
        self._board = Board()
        self._rule_engine = RuleEngine()
        self._audit_log = AuditLog()
        self._current_turn = Color.WHITE

    def submit_move(self, move: Move) -> bool:
        """Submits a move, validates it, and updates the game state."""
        if move.piece.color != self._current_turn:
            print("Error: Not your turn.")
            return False

        if not self._rule_engine.is_move_valid(self._board, move):
            print("Error: Invalid move.")
            return False

        # If valid, apply the move to get a new board state
        self._board = self._board.apply_move(move)
        self._audit_log = self._audit_log.add_move(move)
        self._current_turn = Color.BLACK if self._current_turn == Color.WHITE else Color.WHITE

        print(f"Move successful. It is now {self._current_turn.name}'s turn.")
        print(self._board)
        return True

    def get_board(self) -> Board:
        return self._board

    def get_history(self) -> tuple[Move, ...]:
        return self._audit_log.history

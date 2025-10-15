from models import Move

class AuditLog:
    """A simple, immutable audit log to record game history, similar to a transaction log."""
    def __init__(self, moves: list[Move] | None = None):
        self._moves: tuple[Move, ...] = tuple(moves) if moves else tuple()

    def add_move(self, move: Move) -> 'AuditLog':
        """Returns a new AuditLog instance with the added move."""
        return AuditLog(list(self._moves) + [move])

    @property
    def history(self) -> tuple[Move, ...]:
        return self._moves

    def __str__(self) -> str:
        return "\n".join(f"{i+1}. {move}" for i, move in enumerate(self._moves))

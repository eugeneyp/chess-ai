"""
Material evaluation: the simplest possible chess evaluation function.

A chess engine needs to assign a numeric score to any board position so the
search function can compare moves and choose the best one. This module
implements the most fundamental evaluation: count the material on the board.

Material counting works because pieces have well-established relative values
(a rook is worth roughly 5 pawns, a queen roughly 9). A position where one
side has more material is generally won for that side. This simple heuristic
is surprisingly effective and forms the foundation of all stronger evaluations.

The score is always returned from the perspective of the side to move. This is
the negamax convention: the search always tries to maximize the score, and a
positive score means the current side is ahead. The caller negates the score
when recursing, so the convention propagates automatically.

Future improvements (added in later steps):
- Piece-square tables (PeSTO): positional bonuses for piece placement
- Tapered evaluation: blend middlegame and endgame tables by phase
- Pawn structure: doubled, isolated, and passed pawn penalties/bonuses
- King safety: penalize exposed kings, reward castled/sheltered positions
"""

import chess

from engine.constants import PIECE_VALUES


def evaluate(board: chess.Board) -> int:
    """
    Centipawn evaluation of the current position from the side-to-move's perspective.

    Counts the total material for each side using standard piece values
    (P=100, N=320, B=330, R=500, Q=900). The king is excluded from material
    counting because it can never be traded — its value in constants.py is
    only used for move ordering purposes.

    A positive return value means the side to move is ahead in material.
    A negative return value means the side to move is behind.
    Zero means the position is materially equal (including the starting position).

    Args:
        board: The current board position. Not modified.

    Returns:
        Centipawn score from the side-to-move's perspective.
        Range: roughly -10000 (hopelessly losing) to +10000 (overwhelming advantage).

    Example:
        >>> import chess
        >>> b = chess.Board()
        >>> evaluate(b)  # starting position is equal
        0
        >>> b.remove_piece_at(chess.D8)  # remove black queen
        >>> evaluate(b)  # white to move, white is +900 (a queen ahead)
        900
        >>> b.turn = chess.BLACK
        >>> evaluate(b)  # black to move, black is -900 (a queen behind)
        -900
    """
    white_material = 0
    black_material = 0

    # Sum material for each non-king piece type.
    # board.pieces(piece_type, color) returns a SquareSet; len() gives the count.
    # This is more efficient than iterating over all squares.
    for piece_type in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        value = PIECE_VALUES[piece_type]
        white_material += len(board.pieces(piece_type, chess.WHITE)) * value
        black_material += len(board.pieces(piece_type, chess.BLACK)) * value

    # score > 0 means white is ahead; score < 0 means black is ahead.
    score = white_material - black_material

    # Convert to side-to-move perspective: negate if black is to move.
    return score if board.turn == chess.WHITE else -score

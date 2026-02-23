"""
Engine constants: piece values, search parameters, and table sizes.

All numeric constants used throughout the engine are defined here so that
future modules never need to introduce new magic numbers. Centralizing
constants makes tuning and experimentation much easier.

Piece values follow the standard centipawn convention (1 pawn = 100 cp).
The values here are a reasonable starting point; they can be tuned later
once the engine is strong enough that small material imbalances matter.
"""

import chess

# ---------------------------------------------------------------------------
# Piece values (centipawns)
# ---------------------------------------------------------------------------
# These represent the relative fighting value of each piece type.
# Bishops are slightly stronger than knights in open positions (330 vs 320),
# reflecting the "bishop pair" advantage on open boards.

PAWN_VALUE: int = 100
KNIGHT_VALUE: int = 320
BISHOP_VALUE: int = 330
ROOK_VALUE: int = 500
QUEEN_VALUE: int = 900
KING_VALUE: int = 20_000  # Not used in material counting; guards against king trades

# Mapping from python-chess piece type constants to centipawn values.
# Used by the evaluation function and MVV-LVA move ordering.
PIECE_VALUES: dict[int, int] = {
    chess.PAWN:   PAWN_VALUE,
    chess.KNIGHT: KNIGHT_VALUE,
    chess.BISHOP: BISHOP_VALUE,
    chess.ROOK:   ROOK_VALUE,
    chess.QUEEN:  QUEEN_VALUE,
    chess.KING:   KING_VALUE,
}

# ---------------------------------------------------------------------------
# Special scores
# ---------------------------------------------------------------------------
# Checkmate and draw scores are integers (never floats) so they work
# correctly in alpha-beta comparisons. The exact checkmate score is not
# a concern for random movers, but defining it now avoids surprises later.

CHECKMATE_SCORE: int = 99_999  # Returned when the opponent is checkmated
DRAW_SCORE: int = 0            # Stalemate, repetition, 50-move rule

# ---------------------------------------------------------------------------
# Search parameters
# ---------------------------------------------------------------------------
# MAX_DEPTH caps iterative deepening. In practice, the time limit
# will always terminate the search long before depth 64.
MAX_DEPTH: int = 64

# TIME_CHECK_NODES: how often (in nodes) the search checks the clock.
# Checking every node is too slow (function call overhead); checking too
# rarely means we blow the time budget. 2048 is a good balance.
TIME_CHECK_NODES: int = 2_048

# NULL_MOVE_REDUCTION: depth reduction for null-move pruning (R=3).
# When we skip our turn and the position is still bad for the opponent,
# we prune the branch. R=3 is standard for depths >= 4.
NULL_MOVE_REDUCTION: int = 3

# ---------------------------------------------------------------------------
# Transposition table
# ---------------------------------------------------------------------------
# TT_SIZE: number of entries in the transposition table.
# At ~56 bytes per entry (Python dict overhead), 1M entries ≈ 56 MB.
# This is a reasonable budget for a laptop chess engine.
TT_SIZE: int = 1 << 20  # 1,048,576 entries

# ---------------------------------------------------------------------------
# Time management
# ---------------------------------------------------------------------------
# How much of the allocated time budget the engine is allowed to consume.
# Keeping it at 90% provides a safety margin for OS scheduling jitter
# and the overhead of sending the bestmove reply.
# This is the ONE legitimate float in the entire engine.
TIME_USAGE_FRACTION: float = 0.9

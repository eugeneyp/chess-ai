"""
Tapered PeSTO evaluation: positional scoring with middlegame/endgame interpolation.

A chess engine needs to assign a numeric score to any board position so the
search function can compare moves and choose the best one. This module
implements tapered evaluation using PeSTO piece-square tables (PSTs).

Pure material counting (v3) treats all positions with equal material as equal.
PeSTO adds positional awareness: knights are rewarded for central squares,
rooks are rewarded on open files, kings are rewarded for castled positions in
the middlegame but active central positions in the endgame.

Tapered evaluation blends two separate PST sets:
- Middlegame (MG): prioritizes king safety, piece activity, pawn structure
- Endgame (EG): prioritizes king centralization, passed pawns, rook activity

The blend is controlled by a game-phase score based on remaining non-pawn
material. A fresh position is fully middlegame (phase=24); a K+P vs K endgame
is fully endgame (phase=0). All positions in between are interpolated linearly.

The score is always returned from the perspective of the side to move. This is
the negamax convention: the search always tries to maximize the score, and a
positive score means the current side is ahead. The caller negates the score
when recursing, so the convention propagates automatically.
"""

import chess

from engine.constants import PIECE_VALUES, PST, PHASE_WEIGHTS, MAX_PHASE


def evaluate(board: chess.Board) -> int:
    """
    Tapered centipawn evaluation from the side-to-move's perspective.

    Scores each piece using PeSTO piece-square tables, then interpolates
    between middlegame and endgame scores based on remaining non-pawn material.

    The square indexing convention for PST lookup:
        - White piece on square sq: use index sq ^ 56 (flip rank, since PST
          index 0 = a8 visually but python-chess a1=0 is at the bottom)
        - Black piece on square sq: use index sq directly (already mirrored)

    Args:
        board: The current board position. Not modified.

    Returns:
        Centipawn score from the side-to-move's perspective.
        Positive = side to move is ahead. Range: roughly -10000 to +10000.

    Example:
        >>> import chess
        >>> b = chess.Board()
        >>> evaluate(b)  # starting position should be approximately equal
        0
    """
    mg_score = 0  # middlegame score accumulated (White minus Black)
    eg_score = 0  # endgame score accumulated (White minus Black)
    phase = 0     # game phase: 0 = full endgame, MAX_PHASE = full middlegame

    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None:
            continue

        pt = piece.piece_type
        mg_table, eg_table = PST[pt]

        # King material value is excluded from positional scoring — the king is
        # never traded, so its "value" is only used for move ordering. Only the
        # PST bonus applies for king placement.
        material = 0 if pt == chess.KING else PIECE_VALUES[pt]

        if piece.color == chess.WHITE:
            # Mirror the square vertically: PST row 0 = rank 8 (visual top),
            # but python-chess square 0 = a1 (rank 1). XOR with 56 flips the rank.
            idx = sq ^ 56
            mg_score += material + mg_table[idx]
            eg_score += material + eg_table[idx]
        else:
            # Black pieces: use the square directly (PST is written from Black's
            # perspective already — index 0 = a8 corresponds to a8 for Black).
            idx = sq
            mg_score -= material + mg_table[idx]
            eg_score -= material + eg_table[idx]

        # Accumulate phase counter from non-pawn, non-king pieces.
        phase += PHASE_WEIGHTS.get(pt, 0)

    # Clamp phase to MAX_PHASE (a double queen promotion could theoretically exceed it).
    phase = min(phase, MAX_PHASE)

    # Tapered blend: more phase = more middlegame weight; less phase = more endgame weight.
    # Uses integer arithmetic throughout (no floats).
    tapered = (mg_score * phase + eg_score * (MAX_PHASE - phase)) // MAX_PHASE

    # Convert to side-to-move perspective (negamax convention).
    return tapered if board.turn == chess.WHITE else -tapered

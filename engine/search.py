"""
Search entry point: SearchState and get_best_move.

This module defines the stable public interface that interface/uci.py depends on.
The function signature of get_best_move() is LOCKED — it never changes across
engine versions. Only the internals evolve.

v1 implementation: returns a uniformly random legal move. This establishes the
scaffolding (SearchState, threading model, time handling) without any search
logic. Every future improvement (alpha-beta, quiescence, TT) replaces the body
of get_best_move() while keeping the signature identical.

Threading model:
    The UCI handler starts get_best_move() in a daemon thread. The stop_event
    is set when the GUI sends "stop" or when the time budget expires. The search
    must check stop_event periodically and return the best move found so far.
"""

import random
import threading
from dataclasses import dataclass, field

import chess


@dataclass
class SearchState:
    """
    Mutable state shared between the search thread and the UCI handler.

    Keeping all mutable state in one object (rather than global variables)
    makes the threading model explicit and testable. The UCI handler owns
    this object; the search function reads from and writes to it.

    Attributes:
        stop_event:     Threading event set by the UCI "stop" command or when
                        the time budget expires. The search checks this flag
                        periodically and returns immediately when it is set.
        time_limit_ms:  Absolute deadline expressed as milliseconds budget.
                        The search should not start a new iteration if
                        elapsed time exceeds TIME_USAGE_FRACTION of this value.
        node_count:     Number of positions evaluated in the current search.
                        Used for NPS (nodes per second) reporting.
        best_move:      Best move found so far. Initialized to None; updated
                        each time a deeper iteration completes. Iterative
                        deepening guarantees this is always a legal move even
                        if the search is interrupted mid-iteration.
        best_score:     Centipawn score for best_move from the side-to-move's
                        perspective.
    """

    stop_event: threading.Event = field(default_factory=threading.Event)
    time_limit_ms: float = float("inf")
    node_count: int = 0
    best_move: chess.Move | None = None
    best_score: int = 0


def get_best_move(
    board: chess.Board,
    time_limit_ms: int,
    stop_event: threading.Event,
) -> tuple[chess.Move | None, int, int]:
    """
    Return the best move for the current position within the time budget.

    This is the stable interface called by the UCI handler. The return type
    is always (move, score_cp, depth):
        - move:     The chosen move in chess.Move form, or None if the game
                    is already over (checkmate or stalemate).
        - score_cp: Evaluation in centipawns from the side-to-move's
                    perspective. Positive = side to move is ahead.
        - depth:    The maximum search depth actually reached. For v1 this
                    is always 1 (we look one ply ahead: pick a random move).

    v1 behaviour:
        Select a uniformly random legal move. This is the weakest possible
        engine — it will lose to any human — but it exercises the full
        UCI plumbing, threading model, and time management code paths.

    Args:
        board:         The current position. A copy is NOT made here; the
                       caller is responsible for passing a copy if the
                       original must be preserved.
        time_limit_ms: Time budget in milliseconds. The search must not
                       exceed this limit (within the TIME_USAGE_FRACTION
                       margin defined in constants.py).
        stop_event:    Threading event. When set, the search must return
                       immediately with the best move found so far.

    Returns:
        Tuple of (move, score_cp, depth).
    """
    # Early exit: if the game is already over, there are no legal moves.
    legal_moves = list(board.legal_moves)
    if not legal_moves or stop_event.is_set():
        return (None, 0, 0)

    # v1: pick a random legal move.
    # Score = 0 because we have no evaluation function yet.
    # Depth = 1 because we are looking only at legal moves (no search tree).
    move = random.choice(legal_moves)
    return (move, 0, 1)

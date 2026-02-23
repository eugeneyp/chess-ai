"""
Search entry point: negamax search and get_best_move.

This module defines the stable public interface that interface/uci.py depends on.
The function signature of get_best_move() is LOCKED — it never changes across
engine versions. Only the internals evolve.

v2 implementation: pure negamax to depth 3, no alpha-beta pruning.

Negamax is a simplification of the minimax algorithm that exploits the zero-sum
property of chess: whatever is good for White is equally bad for Black. Instead
of alternating between a maximizing player (White) and a minimizing player
(Black), negamax always maximizes but negates the score returned by each
recursive call. This works because:

    max(a, b) == -min(-a, -b)

So "choose the move that minimizes the opponent's best score" is identical to
"choose the move that maximizes the negation of the opponent's best score."

This baseline (v2) intentionally omits alpha-beta pruning. Without pruning,
negamax explores every node in the game tree — at branching factor ~35 and
depth 3, that is roughly 35^3 = 42,875 nodes per move. Alpha-beta (added in
v3) will reduce this to approximately sqrt(35^3) ≈ 207 nodes with perfect
move ordering, enabling much deeper search within the same time budget.

Threading model:
    The UCI handler starts get_best_move() in a daemon thread. The stop_event
    is set when the GUI sends "stop" or when the time budget expires. The search
    checks stop_event at each node and returns immediately when it is set.
"""

import threading
from dataclasses import dataclass, field

import chess

from engine.constants import CHECKMATE_SCORE
from engine.evaluate import evaluate


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


def negamax(
    board: chess.Board,
    depth: int,
    ply: int,
    state: SearchState,
) -> int:
    """
    Pure negamax search without alpha-beta pruning.

    Recursively explores every legal move to the given depth and returns the
    score of the best line found from the current side-to-move's perspective.
    At depth 0, the position is evaluated statically (material count only).

    This intentionally evaluates ALL nodes — no alpha-beta window, no pruning.
    This makes it slower than the final engine but easier to reason about and
    useful as a correctness baseline: any optimization added later (alpha-beta,
    null-move pruning, etc.) must produce the same scores as this function.

    At ply 0 (the root), the function also stores the best move found in
    state.best_move so that get_best_move() can retrieve it after the search.

    Args:
        board: Current board position. Modified in-place via push/pop.
               The board is always restored to its original state on return.
        depth: Remaining search depth in plies. Decremented by 1 on each
               recursive call. When depth reaches 0, evaluate() is called.
        ply:   Distance from the root (0 at the root, 1 after the first move,
               etc.). Used to encode mate distance in the score so the engine
               prefers faster checkmates: a mate in 1 scores higher than a
               mate in 3.
        state: Shared mutable state (stop_event, node counter, best move).

    Returns:
        The evaluation score in centipawns from the perspective of the side
        to move at this node. Positive means the side to move is winning.
        Returns 0 immediately if stop_event is set (result is discarded).

    Chess programming note:
        Mate scores are encoded as CHECKMATE_SCORE - ply rather than a fixed
        constant. This ensures the engine distinguishes "mate in 1" (score
        99998) from "mate in 3" (score 99996) and always plays the fastest
        available checkmate. The negation on recursion keeps the sign correct:
        if the opponent is mated at ply 3, the score returned at ply 2 is
        -(CHECKMATE_SCORE - 3) = -99996, which the parent negates to +99996.
    """
    # Abort immediately if the search has been cancelled.
    if state.stop_event.is_set():
        return 0

    state.node_count += 1

    # Terminal node: game already decided (checkmate, stalemate, draw by rule).
    # board.is_game_over() handles: checkmate, stalemate, insufficient material,
    # 50-move rule, and threefold repetition. All non-checkmate endings are draws.
    if board.is_game_over():
        if board.is_checkmate():
            # The side to move is IN checkmate, so it loses.
            # Encode distance: prefer being mated later over being mated sooner.
            return -(CHECKMATE_SCORE - ply)
        return 0  # Stalemate or draw

    # Leaf node: evaluate the position statically.
    if depth == 0:
        return evaluate(board)

    best_score = -CHECKMATE_SCORE
    best_move = None

    for move in board.legal_moves:
        board.push(move)
        # Negate the child's score: what is good for the opponent is bad for us.
        score = -negamax(board, depth - 1, ply + 1, state)
        board.pop()

        if score > best_score:
            best_score = score
            best_move = move

    # At the root, save the best move for the caller to retrieve.
    if ply == 0:
        state.best_move = best_move
        state.best_score = best_score

    return best_score


def get_best_move(
    board: chess.Board,
    time_limit_ms: int,
    stop_event: threading.Event,
) -> tuple[chess.Move | None, int, int, int]:
    """
    Return the best move for the current position within the time budget.

    This is the stable interface called by the UCI handler. The return type
    is always (move, score_cp, depth):
        - move:     The chosen move in chess.Move form, or None if the game
                    is already over (checkmate or stalemate).
        - score_cp: Evaluation in centipawns from the side-to-move's
                    perspective. Positive = side to move is ahead.
        - depth:    The maximum search depth actually reached. For v2 this
                    is always 3 (fixed-depth negamax, no iterative deepening).
        - nodes:    Total number of nodes (positions) evaluated during the
                    search. Key metric for comparing pruning effectiveness:
                    v2 (no alpha-beta) evaluates ~8k–43k nodes at depth 3;
                    v3 (with alpha-beta) should evaluate ~200–1000 nodes for
                    the same effective depth with good move ordering.

    v2 behaviour:
        Run pure negamax to depth 3. No alpha-beta pruning, no iterative
        deepening, no time management within the search (the time_limit_ms
        parameter is accepted for API compatibility but not actively used
        beyond the stop_event check within negamax). This makes the search
        predictable and easy to reason about: it always explores the full
        depth-3 tree and returns the objectively best move it can find.

    Args:
        board:         The current position. A copy is NOT made here; the
                       caller is responsible for passing a copy if the
                       original must be preserved.
        time_limit_ms: Time budget in milliseconds. Accepted for API
                       compatibility; the stop_event is the primary
                       interruption mechanism for v2.
        stop_event:    Threading event. When set, the search returns
                       immediately with the best move found so far.

    Returns:
        Tuple of (move, score_cp, depth).
    """
    # Early exit: if the game is already over, there are no legal moves.
    if not any(board.legal_moves) or stop_event.is_set():
        return (None, 0, 0)

    state = SearchState(stop_event=stop_event, time_limit_ms=float(time_limit_ms))

    # Fixed depth 3. Iterative deepening and time management are added in v3.
    negamax(board, depth=3, ply=0, state=state)

    return (state.best_move, state.best_score, 3, state.node_count)

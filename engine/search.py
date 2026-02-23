"""
Search entry point: negamax search with alpha-beta pruning.

This module defines the stable public interface that interface/uci.py depends on.
The function signature of get_best_move() is LOCKED — it never changes across
engine versions. Only the internals evolve.

v3 implementation: negamax with alpha-beta pruning.

Negamax is a simplification of the minimax algorithm that exploits the zero-sum
property of chess: whatever is good for White is equally bad for Black. Instead
of alternating between a maximizing player (White) and a minimizing player
(Black), negamax always maximizes but negates the score returned by each
recursive call. This works because:

    max(a, b) == -min(-a, -b)

Alpha-beta pruning adds a search window [alpha, beta] to eliminate subtrees that
cannot improve the result. The key insight is:

    alpha: the best score the current player can guarantee so far ("lower bound")
    beta:  the best score the opponent can guarantee so far ("upper bound")

When a move scores >= beta, the opponent has a refutation — they would never allow
this position. We can immediately stop searching sibling moves (beta cutoff). This
reduces the worst-case search from O(b^d) to O(b^(d/2)) with perfect move ordering,
effectively doubling the achievable depth for the same time budget.

Compared to v2 (pure negamax): same scores, same move choices, dramatically fewer
nodes. At depth 3 with random ordering, expect 3–10x node reduction. With good
move ordering (added later), up to 50x reduction is achievable.

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
    alpha: int,
    beta: int,
    ply: int,
    state: SearchState,
) -> int:
    """
    Negamax search with alpha-beta pruning.

    Negamax is a simplification of minimax that exploits the zero-sum property
    of chess: one player's gain is exactly the other player's loss. Instead of
    alternating between maximizing and minimizing, negamax always maximizes but
    negates the score returned by recursive calls.

    The alpha-beta window [alpha, beta] prunes branches that cannot influence
    the final decision. If a position scores >= beta, the opponent would never
    allow this position (beta cutoff). If a position scores <= alpha, we already
    have a better option elsewhere.

    Args:
        board: Current board position. Modified in-place via push/pop.
               The board is always restored to its original state on return.
        depth: Remaining search depth in plies. Decremented by 1 on each
               recursive call. When depth reaches 0, evaluate() is called.
        alpha: Lower bound of the search window (best score we can guarantee).
               Raised whenever we find a move that improves our best score.
        beta:  Upper bound of the search window (best score opponent allows).
               If our score exceeds beta, the opponent will avoid this line.
        ply:   Distance from the root (0 at the root, 1 after the first move,
               etc.). Used to encode mate distance in the score so the engine
               prefers faster checkmates: a mate in 1 scores higher than a
               mate in 3.
        state: Shared mutable state (stop_event, node counter, best move).

    Returns:
        The evaluation score in centipawns from the perspective of the side
        to move at this node. Positive means the side to move is winning.
        Returns 0 immediately if stop_event is set (result is discarded).

    Chess programming context:
        Alpha-beta pruning reduces the search tree from O(b^d) to approximately
        O(b^(d/2)) with perfect move ordering, where b is the branching factor
        (~35 in chess) and d is the search depth. This means a depth-6 search
        examines roughly as many nodes as a depth-3 search without pruning.

        Mate scores are encoded as CHECKMATE_SCORE - ply rather than a fixed
        constant. This ensures the engine distinguishes "mate in 1" (score
        99998) from "mate in 3" (score 99996) and always plays the fastest
        available checkmate.
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
        # Swap and negate the window for the child (negamax convention).
        # From the child's perspective: their beta is our alpha (negated),
        # and their alpha is our beta (negated).
        score = -negamax(board, depth - 1, -beta, -alpha, ply + 1, state)
        board.pop()

        if score > best_score:
            best_score = score
            best_move = move

        # Raise the lower bound — we can now guarantee at least best_score.
        if best_score > alpha:
            alpha = best_score

        # Beta cutoff: the opponent has a refutation — they would never allow
        # this line because we already have a score better than what they'd
        # permit. No need to search remaining sibling moves.
        if alpha >= beta:
            break

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
    is always (move, score_cp, depth, nodes):
        - move:     The chosen move in chess.Move form, or None if the game
                    is already over (checkmate or stalemate).
        - score_cp: Evaluation in centipawns from the side-to-move's
                    perspective. Positive = side to move is ahead.
        - depth:    The maximum search depth actually reached. For v3 this
                    is always 3 (fixed-depth negamax, no iterative deepening).
        - nodes:    Total number of nodes (positions) evaluated during the
                    search. Key metric for comparing pruning effectiveness:
                    v2 (no alpha-beta) evaluates ~8k–43k nodes at depth 3;
                    v3 (with alpha-beta) should evaluate ~500–5000 nodes for
                    the same effective depth.

    v3 behaviour:
        Run negamax with alpha-beta pruning to depth 3. Same scores as v2 but
        dramatically fewer nodes searched. The initial window is [-CHECKMATE,
        +CHECKMATE] (a "full-width" search), which is equivalent to pure negamax
        but with pruning when clearly bad moves are found.

    Args:
        board:         The current position. A copy is NOT made here; the
                       caller is responsible for passing a copy if the
                       original must be preserved.
        time_limit_ms: Time budget in milliseconds. Accepted for API
                       compatibility; the stop_event is the primary
                       interruption mechanism for v3.
        stop_event:    Threading event. When set, the search returns
                       immediately with the best move found so far.

    Returns:
        Tuple of (move, score_cp, depth, nodes).
    """
    # Early exit: if the game is already over, there are no legal moves.
    if not any(board.legal_moves) or stop_event.is_set():
        return (None, 0, 0, 0)

    state = SearchState(stop_event=stop_event, time_limit_ms=float(time_limit_ms))

    # Full-width alpha-beta search (initial window spans all possible scores).
    negamax(board, depth=3, alpha=-CHECKMATE_SCORE, beta=CHECKMATE_SCORE, ply=0, state=state)

    return (state.best_move, state.best_score, 3, state.node_count)

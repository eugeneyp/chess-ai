"""
Search entry point: negamax with alpha-beta pruning, quiescence search,
MVV-LVA move ordering, and iterative deepening with time management.

This module defines the stable public interface that interface/uci.py depends on.
The function signature of get_best_move() is LOCKED — it never changes across
engine versions. Only the internals evolve.

v4 implementation adds four improvements over v3:

1. MVV-LVA move ordering: captures are searched first, prioritizing high-value
   victims captured by low-value attackers (e.g., PxQ before QxP). This maximizes
   alpha-beta cutoffs, effectively doubling the reachable search depth.

2. Quiescence search: at depth 0, instead of returning a static evaluation, we
   continue searching captures until the position is "quiet." This eliminates the
   horizon effect — e.g., v3 would evaluate mid-exchange and think it won a piece,
   missing the recapture on the next move.

3. PeSTO piece-square tables: evaluation now includes positional bonuses that guide
   pieces toward good squares (knights to the center, kings to safety, etc.). The
   evaluation is tapered between middlegame and endgame PSTs based on remaining
   material.

4. Iterative deepening: the engine searches depth 1, 2, 3, ... until time runs out.
   Each completed iteration provides a valid move to return if interrupted. Deeper
   iterations also benefit from the move ordering hints from shallower searches
   (though we haven't added TT best-move ordering yet).

Threading model:
    The UCI handler starts get_best_move() in a daemon thread. The stop_event
    is set when the GUI sends "stop" or when the time budget expires. The search
    checks stop_event at each node and returns immediately when it is set.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Iterable

import chess

from engine.constants import (
    CHECKMATE_SCORE,
    MAX_DEPTH,
    PIECE_VALUES,
    TIME_CHECK_NODES,
    TIME_USAGE_FRACTION,
)
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
        start_time:     Monotonic clock timestamp when the search began.
                        Used for time management checks.
    """

    stop_event: threading.Event = field(default_factory=threading.Event)
    time_limit_ms: float = float("inf")
    node_count: int = 0
    best_move: chess.Move | None = None
    best_score: int = 0
    start_time: float = field(default_factory=time.monotonic)


def _order_moves(board: chess.Board, moves: Iterable[chess.Move]) -> list[chess.Move]:
    """
    Order moves for better alpha-beta pruning using MVV-LVA for captures.

    MVV-LVA (Most Valuable Victim - Least Valuable Aggressor) is a simple but
    effective heuristic: search captures of high-value pieces first, and prefer
    to capture with low-value pieces (they're less risky). For example:
        - PxQ scores highest (cheap attacker, expensive victim)
        - QxP scores lowest among captures (expensive attacker, cheap victim)
        - Quiet moves are searched last (score 0)

    This ordering dramatically improves alpha-beta efficiency because captures
    that win material tend to raise alpha quickly, pruning the remaining siblings.

    Score formula:
        captures: 10_000 + victim_value - attacker_value  (always > 0)
        quiet moves: 0

    Args:
        board: The current board position (used to look up piece types).
        moves: Legal moves to order.

    Returns:
        List of moves sorted from highest to lowest score.
    """
    def _mvv_lva_score(move: chess.Move) -> int:
        if not board.is_capture(move):
            return 0
        attacker = board.piece_at(move.from_square)
        victim = board.piece_at(move.to_square)
        attacker_val = PIECE_VALUES.get(attacker.piece_type, 0) if attacker else 0
        # En passant: the captured pawn is not on move.to_square; default to pawn value.
        victim_val = PIECE_VALUES.get(victim.piece_type, 0) if victim else PIECE_VALUES[chess.PAWN]
        return 10_000 + victim_val - attacker_val

    return sorted(moves, key=_mvv_lva_score, reverse=True)


def quiescence(
    board: chess.Board,
    alpha: int,
    beta: int,
    ply: int,
    state: SearchState,
) -> int:
    """
    Quiescence search: resolves tactical instability at leaf nodes.

    The "horizon effect" occurs when the fixed-depth search evaluates a position
    mid-exchange. For example, at depth 4, the engine might see it captures a knight
    (good!) but not the recapture on move 5 (bad). Quiescence search fixes this by
    continuing to search captures until the position is "quiet" (no captures left).

    Stand-pat: the side to move can always choose NOT to capture. The static
    evaluation serves as a lower bound — if it already exceeds beta, we prune
    immediately (the opponent would never allow this position). If it exceeds alpha,
    we raise alpha (we found a quiet move better than any previous option).

    Only captures are searched (not all legal moves). This keeps the tree manageable.
    Promotions are also captures in most cases; we include any capturing move.

    Args:
        board: Current board position. Modified in-place via push/pop.
        alpha: Lower bound of the search window.
        beta:  Upper bound of the search window.
        ply:   Distance from the root (used for mate distance encoding).
        state: Shared mutable state (stop_event, node counter).

    Returns:
        Score in centipawns from the perspective of the side to move.
    """
    if state.stop_event.is_set():
        return 0

    state.node_count += 1

    # Time check: quiescence can dominate node counts in tactical positions,
    # so we must check time here too — not only in negamax. Without this check,
    # a shallow depth with few negamax nodes but thousands of quiescence nodes
    # will never trigger the negamax time check and runs completely unconstrained.
    if state.node_count % TIME_CHECK_NODES == 0:
        elapsed_ms = (time.monotonic() - state.start_time) * 1000
        if elapsed_ms >= state.time_limit_ms * TIME_USAGE_FRACTION:
            state.stop_event.set()
            return 0

    # Stand-pat: evaluate the position without making any capture.
    # If the static eval already beats beta, we can prune immediately.
    stand_pat = evaluate(board)
    if stand_pat >= beta:
        return beta
    if stand_pat > alpha:
        alpha = stand_pat

    # Search captures only (ordered by MVV-LVA to find good captures first).
    captures = [m for m in board.legal_moves if board.is_capture(m)]
    for move in _order_moves(board, captures):
        board.push(move)
        score = -quiescence(board, -beta, -alpha, ply + 1, state)
        board.pop()

        if score >= beta:
            return beta
        if score > alpha:
            alpha = score

    return alpha


def negamax(
    board: chess.Board,
    depth: int,
    alpha: int,
    beta: int,
    ply: int,
    state: SearchState,
) -> int:
    """
    Negamax search with alpha-beta pruning and quiescence search at leaf nodes.

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
               recursive call. When depth reaches 0, drops into quiescence search.
        alpha: Lower bound of the search window (best score we can guarantee).
               Raised whenever we find a move that improves our best score.
        beta:  Upper bound of the search window (best score opponent allows).
               If our score exceeds beta, the opponent will avoid this line.
        ply:   Distance from the root (0 at the root, 1 after the first move).
               Used to encode mate distance in the score so the engine prefers
               faster checkmates: a mate in 1 scores higher than a mate in 3.
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

    # Periodic time check: avoid the overhead of checking every node.
    # Every TIME_CHECK_NODES nodes, measure elapsed time and stop if over budget.
    if state.node_count % TIME_CHECK_NODES == 0:
        elapsed_ms = (time.monotonic() - state.start_time) * 1000
        if elapsed_ms >= state.time_limit_ms * TIME_USAGE_FRACTION:
            state.stop_event.set()
            return 0

    # Terminal node: game already decided (checkmate, stalemate, draw by rule).
    # board.is_game_over() handles: checkmate, stalemate, insufficient material,
    # 50-move rule, and threefold repetition. All non-checkmate endings are draws.
    if board.is_game_over():
        if board.is_checkmate():
            # The side to move is IN checkmate, so it loses.
            # Encode distance: prefer being mated later over being mated sooner.
            return -(CHECKMATE_SCORE - ply)
        return 0  # Stalemate or draw

    # Leaf node: drop into quiescence search to resolve captures.
    # This eliminates the horizon effect — we don't stop mid-exchange.
    if depth == 0:
        return quiescence(board, alpha, beta, ply, state)

    best_score = -CHECKMATE_SCORE
    best_move = None

    # MVV-LVA move ordering: search captures first (ordered by victim/attacker value),
    # then quiet moves. Better ordering → more alpha-beta cutoffs → fewer nodes.
    for move in _order_moves(board, board.legal_moves):
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

    Uses iterative deepening: searches depth 1, 2, 3, ... until the time budget
    is exhausted. Each completed iteration guarantees a valid best move to return
    even if the next iteration is interrupted partway through.

    This is the stable interface called by the UCI handler. The return type
    is always (move, score_cp, depth, nodes):
        - move:     The chosen move in chess.Move form, or None if the game
                    is already over (checkmate or stalemate).
        - score_cp: Evaluation in centipawns from the side-to-move's
                    perspective. Positive = side to move is ahead.
        - depth:    The maximum search depth that fully completed.
        - nodes:    Total number of nodes (positions) evaluated during the
                    search. Key metric for comparing search efficiency.

    v4 behaviour:
        Iterative deepening from depth 1 to MAX_DEPTH. At each depth, runs
        negamax with alpha-beta, quiescence search, and MVV-LVA move ordering.
        Stops when time budget is ~90% consumed or stop_event is set.

    Args:
        board:         The current position. Not modified.
        time_limit_ms: Time budget in milliseconds.
        stop_event:    Threading event. When set, returns immediately with
                       the best move found so far.

    Returns:
        Tuple of (move, score_cp, depth, nodes).
    """
    # Early exit: if the game is already over, there are no legal moves.
    if not any(board.legal_moves) or stop_event.is_set():
        return (None, 0, 0, 0)

    state = SearchState(
        stop_event=stop_event,
        time_limit_ms=float(time_limit_ms),
        start_time=time.monotonic(),
    )

    completed_depth = 0

    for depth in range(1, MAX_DEPTH + 1):
        # Don't start a new iteration if we've already used most of the time budget.
        elapsed_ms = (time.monotonic() - state.start_time) * 1000
        if elapsed_ms >= state.time_limit_ms * TIME_USAGE_FRACTION:
            break

        # Save the previous iteration's result before overwriting (in case this
        # iteration is interrupted midway and produces an incomplete result).
        prev_best_move = state.best_move
        prev_best_score = state.best_score

        negamax(board, depth, -CHECKMATE_SCORE, CHECKMATE_SCORE, 0, state)

        if state.stop_event.is_set():
            # This iteration was interrupted — restore the last complete result.
            if prev_best_move is not None:
                state.best_move = prev_best_move
                state.best_score = prev_best_score
            break

        completed_depth = depth

    return (state.best_move, state.best_score, completed_depth, state.node_count)

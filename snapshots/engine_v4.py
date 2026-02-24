"""
ChessAI v4 snapshot — negamax with alpha-beta, quiescence search, MVV-LVA
move ordering, PeSTO piece-square tables, and iterative deepening.

Standalone UCI script. Self-contained: no imports from engine/.
Frozen at the state of the codebase after Step 4.

Strength improvements over v3 (~768 ELO):
  - PeSTO piece-square tables: positional awareness (+200–400 ELO)
  - Quiescence search: eliminates horizon effect (+200–400 ELO)
  - MVV-LVA move ordering: better capture ordering (+100–200 ELO)
  - Iterative deepening: reaches deeper in budget time (+50–100 ELO)
  Expected combined: first real wins against Stockfish-1320 (~1300+ ELO)

Used as the baseline for Step 5 SPRT benchmarks.
"""

import sys
import os
import threading
import time
from typing import Iterable

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import chess

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAWN_VALUE: int = 100
KNIGHT_VALUE: int = 320
BISHOP_VALUE: int = 330
ROOK_VALUE: int = 500
QUEEN_VALUE: int = 900
KING_VALUE: int = 20_000

PIECE_VALUES: dict[int, int] = {
    chess.PAWN:   PAWN_VALUE,
    chess.KNIGHT: KNIGHT_VALUE,
    chess.BISHOP: BISHOP_VALUE,
    chess.ROOK:   ROOK_VALUE,
    chess.QUEEN:  QUEEN_VALUE,
    chess.KING:   KING_VALUE,
}

CHECKMATE_SCORE: int = 99_999
MAX_DEPTH: int = 64
TIME_CHECK_NODES: int = 2_048
TIME_USAGE_FRACTION: float = 0.9

# ---------------------------------------------------------------------------
# PeSTO piece-square tables
# ---------------------------------------------------------------------------
# Index 0 = a8, index 63 = h1 (visual board, rank 8 at top).
# White piece on python-chess square sq: use sq ^ 56 (flip rank).
# Black piece on square sq: use sq directly.

MG_PAWN_TABLE: list[int] = [
     0,   0,   0,   0,   0,   0,   0,   0,
    98, 134,  61,  95,  68, 126,  34, -11,
    -6,   7,  26,  31,  65,  56,  25, -20,
   -14,  13,   6,  21,  23,  12,  17, -23,
   -27,  -2,  -5,  12,  17,   6,  10, -25,
   -26,  -4,  -4, -10,   3,   3,  33, -12,
   -35,  -1, -20, -23, -15,  24,  38, -22,
     0,   0,   0,   0,   0,   0,   0,   0,
]
EG_PAWN_TABLE: list[int] = [
     0,   0,   0,   0,   0,   0,   0,   0,
   178, 173, 158, 134, 147, 132, 165, 187,
    94, 100,  85,  67,  56,  53,  82,  84,
    32,  24,  13,   5,  -2,   4,  17,  17,
    13,   9,  -3,  -7,  -7,  -8,   3,  -1,
     4,   7,  -6,   1,   0,  -5,  -1,  -8,
    13,   8,   8,  10,  13,   0,   2,  -7,
     0,   0,   0,   0,   0,   0,   0,   0,
]
MG_KNIGHT_TABLE: list[int] = [
   -167, -89, -34, -49,  61, -97, -15, -107,
    -73, -41,  72,  36,  23,  62,   7,  -17,
    -47,  60,  37,  65,  84, 129,  73,   44,
     -9,  17,  19,  53,  37,  69,  18,   22,
    -13,   4,  16,  13,  28,  19,  21,   -8,
    -23,  -9,  12,  10,  19,  17,  25,  -16,
    -29, -53, -12,  -3,  -1,  18, -14,  -19,
   -105, -21, -58, -33, -17, -28, -19,  -23,
]
EG_KNIGHT_TABLE: list[int] = [
   -58, -38, -13, -28, -31, -27, -63, -99,
   -25,  -8, -25,  -2,  -9, -25, -24, -52,
   -24, -20,  10,   9,  -1,  -9, -19, -41,
   -17,   3,  22,  22,  22,  11,   8, -18,
   -18,  -6,  16,  25,  16,  17,   4, -18,
   -23,  -3,  -1,  15,  10,  -3, -20, -22,
   -42, -20, -10,  -5,  -2, -20, -23, -44,
   -29, -51, -23, -15, -22, -18, -50, -64,
]
MG_BISHOP_TABLE: list[int] = [
   -29,   4, -82, -37, -25, -42,   7,  -8,
   -26,  16, -18, -13,  30,  59,  18, -47,
   -16,  37,  43,  40,  35,  50,  37,  -2,
    -4,   5,  19,  50,  37,  37,   7,  -2,
    -6,  13,  13,  26,  34,  12,  10,   4,
     0,  15,  15,  15,  14,  27,  18,  10,
     4,  15,  16,   0,   7,  21,  33,   1,
   -33,  -3, -14, -21, -13, -12, -39, -21,
]
EG_BISHOP_TABLE: list[int] = [
   -14, -21, -11,  -8,  -7,  -9, -17, -24,
    -8,  -4,   7, -12,  -3, -13,  -4, -14,
     2,  -8,   0,  -1,  -2,   6,   0,   4,
    -3,   9,  12,   9,  14,  10,   3,   2,
    -6,   3,  13,  19,   7,  10,  -3,  -9,
   -12,  -3,   8,  10,  13,   3,  -7, -15,
   -14, -18,  -7,  -1,   4,  -9, -15, -27,
   -23,  -9, -23,  -5,  -9, -16,  -5, -17,
]
MG_ROOK_TABLE: list[int] = [
    32,  42,  32,  51,  63,   9,  31,  43,
    27,  32,  58,  62,  80,  67,  26,  44,
    -5,  19,  26,  36,  17,  45,  61,  16,
   -24, -11,   7,  26,  24,  35,  -8, -20,
   -36, -26, -12,  -1,   9,  -7,   6, -23,
   -45, -25, -16, -17,   3,   0,  -5, -33,
   -44, -16, -20,  -9,  -1,  11,  -6, -71,
   -19, -13,   1,  17,  16,   7, -37, -26,
]
EG_ROOK_TABLE: list[int] = [
    13,  10,  18,  15,  12,  12,   8,   5,
    11,  13,  13,  11,  -3,   3,   8,   3,
     7,   7,   7,   5,   4,  -3,  -5,  -3,
     4,   3,  13,   1,   2,   1,  -1,   2,
     3,   5,   8,   4,  -5,  -6,  -8, -11,
    -4,   0,  -5,  -1,  -7, -12,  -8, -16,
    -6,  -6,   0,   2,  -9,  -9, -11,  -3,
    -9,   2,   3,  -1,  -5, -13,   4, -20,
]
MG_QUEEN_TABLE: list[int] = [
   -28,   0,  29,  12,  59,  44,  43,  45,
   -24, -39,  -5,   1, -16,  57,  28,  54,
   -13, -17,   7,   8,  29,  56,  47,  57,
   -27, -27, -16, -16,  -1,  17,  -2,   1,
    -9, -26,  -9, -10,  -2,  -4,   3,  -3,
   -14,   2, -11,  -2,  -5,   2,  14,   5,
   -35,  -8,  11,   2,   8,  15,  -3,   1,
    -1, -18,  -9,  10, -15, -25, -31, -50,
]
EG_QUEEN_TABLE: list[int] = [
    -9,  22,  22,  27,  27,  19,  10,  20,
   -17,  20,  32,  41,  58,  25,  30,   0,
   -20,   6,   9,  49,  47,  35,  19,   9,
     3,  22,  24,  45,  57,  40,  57,  36,
   -18,  28,  19,  47,  31,  34,  39,  23,
   -16, -27,  15,   6,   9,  17,  10,   5,
   -22, -23, -30, -16, -16, -23, -36, -32,
   -33, -28, -22, -43,  -5, -32, -20, -41,
]
MG_KING_TABLE: list[int] = [
   -65,  23,  16, -15, -56, -34,   2,  13,
    29,  -1, -20,  -7,  -8,  -4, -38, -29,
    -9,  24,   2, -16, -20,   6,  22, -22,
   -17, -20, -12, -27, -30, -25, -14, -36,
   -49,  -1, -27, -39, -46, -44, -33, -51,
   -14, -14, -22, -46, -44, -30, -15, -27,
     1,   7,  -8, -64, -43, -16,   9,   8,
   -15,  36,  12, -54,   8, -28,  24,  14,
]
EG_KING_TABLE: list[int] = [
   -74, -35, -18, -18, -11,  15,   4, -17,
   -12,  17,  14,  17,  17,  38,  23,  11,
    10,  17,  23,  15,  20,  45,  44,  13,
    -8,  22,  24,  27,  26,  33,  26,   3,
   -18,  -4,  21,  24,  27,  23,   9, -11,
   -19,  -3,  11,  21,  23,  16,   7,  -9,
   -27, -11,   4,  13,  14,   4,  -5, -17,
   -53, -34, -21, -11, -28, -14, -24, -43,
]

PST: dict[int, tuple[list[int], list[int]]] = {
    chess.PAWN:   (MG_PAWN_TABLE,   EG_PAWN_TABLE),
    chess.KNIGHT: (MG_KNIGHT_TABLE, EG_KNIGHT_TABLE),
    chess.BISHOP: (MG_BISHOP_TABLE, EG_BISHOP_TABLE),
    chess.ROOK:   (MG_ROOK_TABLE,   EG_ROOK_TABLE),
    chess.QUEEN:  (MG_QUEEN_TABLE,  EG_QUEEN_TABLE),
    chess.KING:   (MG_KING_TABLE,   EG_KING_TABLE),
}

PHASE_WEIGHTS: dict[int, int] = {
    chess.PAWN:   0,
    chess.KNIGHT: 1,
    chess.BISHOP: 1,
    chess.ROOK:   2,
    chess.QUEEN:  4,
    chess.KING:   0,
}
MAX_PHASE: int = 24

# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate(board: chess.Board) -> int:
    """Tapered PeSTO evaluation from side-to-move perspective (centipawns)."""
    mg_score = 0
    eg_score = 0
    phase = 0

    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None:
            continue
        pt = piece.piece_type
        mg_table, eg_table = PST[pt]
        material = 0 if pt == chess.KING else PIECE_VALUES[pt]

        if piece.color == chess.WHITE:
            idx = sq ^ 56
            mg_score += material + mg_table[idx]
            eg_score += material + eg_table[idx]
        else:
            idx = sq
            mg_score -= material + mg_table[idx]
            eg_score -= material + eg_table[idx]

        phase += PHASE_WEIGHTS.get(pt, 0)

    phase = min(phase, MAX_PHASE)
    tapered = (mg_score * phase + eg_score * (MAX_PHASE - phase)) // MAX_PHASE
    return tapered if board.turn == chess.WHITE else -tapered


# ---------------------------------------------------------------------------
# Move ordering
# ---------------------------------------------------------------------------


def _order_moves(board: chess.Board, moves: Iterable[chess.Move]) -> list[chess.Move]:
    """Order moves by MVV-LVA: captures first (high-value victim, low-value attacker)."""
    def _score(move: chess.Move) -> int:
        if not board.is_capture(move):
            return 0
        attacker = board.piece_at(move.from_square)
        victim = board.piece_at(move.to_square)
        attacker_val = PIECE_VALUES.get(attacker.piece_type, 0) if attacker else 0
        victim_val = PIECE_VALUES.get(victim.piece_type, 0) if victim else PIECE_VALUES[chess.PAWN]
        return 10_000 + victim_val - attacker_val

    return sorted(moves, key=_score, reverse=True)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def quiescence(board: chess.Board, alpha: int, beta: int, ply: int, state: dict) -> int:
    """
    Quiescence search: continue searching captures until position is quiet.

    Stand-pat: static evaluation serves as a lower bound (we can always stop here).
    If stand_pat >= beta, prune immediately. Otherwise search captures.
    """
    if state["stop"].is_set():
        return 0

    state["nodes"] += 1

    stand_pat = evaluate(board)
    if stand_pat >= beta:
        return beta
    if stand_pat > alpha:
        alpha = stand_pat

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


def negamax(board: chess.Board, depth: int, alpha: int, beta: int, ply: int, state: dict) -> int:
    """
    Negamax with alpha-beta pruning. Returns score from side-to-move perspective.

    At depth 0, drops into quiescence search. Uses MVV-LVA move ordering.
    Checks time every TIME_CHECK_NODES nodes.
    """
    if state["stop"].is_set():
        return 0

    state["nodes"] += 1

    # Periodic time check
    if state["nodes"] % TIME_CHECK_NODES == 0:
        elapsed_ms = (time.monotonic() - state["start_time"]) * 1000
        if elapsed_ms >= state["time_limit_ms"] * TIME_USAGE_FRACTION:
            state["stop"].set()
            return 0

    if board.is_game_over():
        return -(CHECKMATE_SCORE - ply) if board.is_checkmate() else 0

    if depth == 0:
        return quiescence(board, alpha, beta, ply, state)

    best_score = -CHECKMATE_SCORE
    best_move = None

    for move in _order_moves(board, board.legal_moves):
        board.push(move)
        score = -negamax(board, depth - 1, -beta, -alpha, ply + 1, state)
        board.pop()

        if score > best_score:
            best_score = score
            best_move = move

        if best_score > alpha:
            alpha = best_score

        if alpha >= beta:
            break

    if ply == 0:
        state["best_move"] = best_move
        state["best_score"] = best_score

    return best_score


def get_best_move(board: chess.Board, time_limit_ms: int, stop_event: threading.Event):
    """
    Iterative deepening search. Returns (move, score_cp, depth).

    Searches depth 1, 2, 3, ... until time runs out or stop_event is set.
    Each completed iteration guarantees a valid best move.
    """
    if not any(board.legal_moves) or stop_event.is_set():
        return (None, 0, 0)

    start_time = time.monotonic()
    state = {
        "stop": stop_event,
        "nodes": 0,
        "best_move": None,
        "best_score": 0,
        "time_limit_ms": float(time_limit_ms),
        "start_time": start_time,
    }

    completed_depth = 0

    for depth in range(1, MAX_DEPTH + 1):
        elapsed_ms = (time.monotonic() - start_time) * 1000
        if elapsed_ms >= float(time_limit_ms) * TIME_USAGE_FRACTION:
            break

        prev_best_move = state["best_move"]
        prev_best_score = state["best_score"]

        negamax(board, depth, -CHECKMATE_SCORE, CHECKMATE_SCORE, 0, state)

        if state["stop"].is_set():
            if prev_best_move is not None:
                state["best_move"] = prev_best_move
                state["best_score"] = prev_best_score
            break

        completed_depth = depth

    return (state["best_move"], state["best_score"], completed_depth)


# ---------------------------------------------------------------------------
# UCI handler
# ---------------------------------------------------------------------------


def _send(line: str) -> None:
    print(line, flush=True)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _parse_go_time(tokens: list[str], turn: bool) -> int:
    params: dict[str, int] = {}
    i = 0
    while i < len(tokens) - 1:
        try:
            params[tokens[i]] = int(tokens[i + 1])
            i += 2
        except (ValueError, IndexError):
            i += 1
    if "movetime" in params:
        return params["movetime"]
    time_key = "wtime" if turn == chess.WHITE else "btime"
    inc_key = "winc" if turn == chess.WHITE else "binc"
    if time_key in params:
        return max(1, params[time_key] // 40 + params.get(inc_key, 0))
    return 10_000_000


def run_uci_loop() -> None:
    board = chess.Board()
    search_thread: threading.Thread | None = None
    stop_event = threading.Event()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        tokens = line.split()
        cmd = tokens[0]
        args = tokens[1:]

        try:
            if cmd == "uci":
                _send("id name ChessAI-v4")
                _send("id author Chess AI Project")
                _send("uciok")

            elif cmd == "isready":
                _send("readyok")

            elif cmd == "ucinewgame":
                stop_event.set()
                if search_thread and search_thread.is_alive():
                    search_thread.join(timeout=2.0)
                board = chess.Board()
                stop_event = threading.Event()

            elif cmd == "position":
                if not args:
                    continue
                if args[0] == "startpos":
                    board = chess.Board()
                    move_tokens = args[2:] if len(args) > 1 and args[1] == "moves" else []
                elif args[0] == "fen":
                    if "moves" in args:
                        idx = args.index("moves")
                        board = chess.Board(" ".join(args[1:idx]))
                        move_tokens = args[idx + 1:]
                    else:
                        board = chess.Board(" ".join(args[1:]))
                        move_tokens = []
                else:
                    continue
                for uci_move in move_tokens:
                    m = chess.Move.from_uci(uci_move)
                    if m in board.legal_moves:
                        board.push(m)

            elif cmd == "go":
                stop_event.set()
                if search_thread and search_thread.is_alive():
                    search_thread.join(timeout=2.0)
                stop_event = threading.Event()
                time_ms = _parse_go_time(args, board.turn)
                board_copy = board.copy()
                _stop = stop_event

                def _run(b=board_copy, ms=time_ms, s=_stop):
                    try:
                        t0 = time.monotonic()
                        move, score, depth = get_best_move(b, ms, s)
                        elapsed = max(1, int((time.monotonic() - t0) * 1000))
                        nodes = 1  # approximate; state not accessible here
                        if move is not None:
                            _send(f"info depth {depth} score cp {score} nodes {nodes} nps 1 time {elapsed}")
                            _send(f"bestmove {move.uci()}")
                        else:
                            _send("bestmove (none)")
                    except Exception as e:
                        _log(f"search error: {e}")
                        _send("bestmove (none)")

                search_thread = threading.Thread(target=_run, daemon=True)
                search_thread.start()

            elif cmd == "stop":
                stop_event.set()
                if search_thread and search_thread.is_alive():
                    search_thread.join(timeout=2.0)

            elif cmd == "quit":
                stop_event.set()
                sys.exit(0)

        except Exception as e:
            _log(f"error handling {cmd!r}: {e}")


if __name__ == "__main__":
    run_uci_loop()

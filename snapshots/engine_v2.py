"""
ChessAI v2 snapshot — pure negamax depth 3, material evaluation.

Standalone UCI script. Self-contained: no imports from engine/.
Frozen at the state of the codebase after Step 2.

Strength: estimated ~600–900 ELO (pure negamax, no alpha-beta).
  - Searches all nodes to depth 3 (~42,875 nodes per move at branching factor 35)
  - Evaluates positions by material count only (P=100, N=320, B=330, R=500, Q=900)
  - Detects checkmate and encodes mate distance in scores
  - No alpha-beta pruning, no quiescence search, no iterative deepening

Used as the baseline for Step 3 (alpha-beta pruning) SPRT benchmarks.
"""

import sys
import os
import threading
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import chess

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIECE_VALUES: dict[int, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
}
CHECKMATE_SCORE: int = 99_999

# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate(board: chess.Board) -> int:
    """Material count from side-to-move perspective (centipawns)."""
    white = sum(
        len(board.pieces(pt, chess.WHITE)) * v for pt, v in PIECE_VALUES.items()
    )
    black = sum(
        len(board.pieces(pt, chess.BLACK)) * v for pt, v in PIECE_VALUES.items()
    )
    score = white - black
    return score if board.turn == chess.WHITE else -score


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def negamax(board: chess.Board, depth: int, ply: int, state: dict) -> int:
    """Pure negamax (no alpha-beta). Returns score from side-to-move perspective."""
    if state["stop"].is_set():
        return 0

    state["nodes"] += 1

    if board.is_game_over():
        return -(CHECKMATE_SCORE - ply) if board.is_checkmate() else 0

    if depth == 0:
        return evaluate(board)

    best_score = -CHECKMATE_SCORE
    best_move = None

    for move in board.legal_moves:
        board.push(move)
        score = -negamax(board, depth - 1, ply + 1, state)
        board.pop()
        if score > best_score:
            best_score = score
            best_move = move

    if ply == 0:
        state["best_move"] = best_move
        state["best_score"] = best_score

    return best_score


def get_best_move(board: chess.Board, time_limit_ms: int, stop_event: threading.Event):
    """Run negamax to depth 3 and return (move, score_cp, depth)."""
    if not any(board.legal_moves) or stop_event.is_set():
        return (None, 0, 0)

    state = {"stop": stop_event, "nodes": 0, "best_move": None, "best_score": 0}
    negamax(board, depth=3, ply=0, state=state)
    return (state["best_move"], state["best_score"], 3)


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
                _send("id name ChessAI-v2")
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
                        if move is not None:
                            _send(f"info depth {depth} score cp {score} nodes 1 nps 1 time {elapsed}")
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

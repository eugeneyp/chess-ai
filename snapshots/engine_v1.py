"""
ChessAI v1 snapshot — random legal move engine.

Standalone UCI script. Self-contained: no imports from engine/.
Frozen at the state of the codebase after Step 1 (commit aa21743).

Strength: ~0 ELO (plays uniformly random legal moves).
Used as the baseline for all future SPRT benchmarks.
"""

import random
import sys
import os
import threading
import time

# Ensure chess is importable whether run directly or from the repo root
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import chess

# ---------------------------------------------------------------------------
# Engine logic
# ---------------------------------------------------------------------------


def get_best_move(board: chess.Board, time_limit_ms: int, stop_event: threading.Event):
    """Return a uniformly random legal move."""
    legal_moves = list(board.legal_moves)
    if not legal_moves or stop_event.is_set():
        return (None, 0, 0)
    return (random.choice(legal_moves), 0, 1)


# ---------------------------------------------------------------------------
# UCI handler (minimal, identical protocol to production interface/uci.py)
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
                _send("id name ChessAI-v1")
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
                            nps = max(1, 1000 // elapsed)
                            _send(f"info depth {depth} score cp {score} nodes 1 nps {nps} time {elapsed}")
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

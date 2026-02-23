"""
UCI (Universal Chess Interface) protocol handler.

UCI is the standard text-based protocol that allows chess GUIs and testing
tools (like cutechess-cli) to communicate with chess engines. The engine
reads commands from stdin and writes responses to stdout. All output lines
must be flushed immediately — GUI programs won't block waiting for a newline.

Protocol overview:
    GUI → Engine: uci, isready, ucinewgame, position, go, stop, quit
    Engine → GUI: id name, id author, uciok, readyok, info, bestmove

Threading model:
    The UCI loop runs on the main thread and must never block on the search.
    When the GUI sends "go", we spawn a daemon thread to run the search.
    The main thread continues reading stdin so it can handle "stop" at any time.
    A threading.Event (stop_event) signals the search thread to terminate early.

Critical rule: NEVER print to stdout except for valid UCI responses.
Debug output must go to stderr or be suppressed entirely.
"""

import sys
import os
import threading
import time

# ---------------------------------------------------------------------------
# Path setup: make 'engine' importable when this script is run directly.
# When run as `python interface/uci.py` from the repo root, sys.path may not
# include the repo root, so `import engine` would fail. We fix this by
# inserting the parent directory of this file's parent directory (the repo
# root) at the front of sys.path.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import chess
from engine.search import SearchState, get_best_move


def _send(line: str) -> None:
    """
    Write a line to stdout and flush immediately.

    UCI requires every output line to be flushed right away. GUIs read
    line-by-line; if the buffer is not flushed, the GUI will hang waiting
    for output that is already in the buffer.

    Args:
        line: The UCI response line to send (without trailing newline).
    """
    print(line, flush=True)


def _log(message: str) -> None:
    """
    Write a debug/error message to stderr.

    In UCI mode, stdout is reserved for valid protocol messages. Any debug
    output sent to stdout will confuse the GUI and corrupt the protocol.
    All diagnostic output goes to stderr instead.

    Args:
        message: The log message (without trailing newline).
    """
    print(message, file=sys.stderr, flush=True)


class UciHandler:
    """
    Stateful handler for the UCI protocol.

    Holds the current board position and manages the search thread lifecycle.
    The main UCI loop creates one instance and dispatches commands to it.

    Attributes:
        board:        The current board position, updated by "position" commands.
        search_thread: The active search thread, or None if no search is running.
        stop_event:   Threading event shared with the search thread. Set to
                      signal the search to stop.
    """

    def __init__(self) -> None:
        self.board: chess.Board = chess.Board()
        self.search_thread: threading.Thread | None = None
        self.stop_event: threading.Event = threading.Event()

    # -----------------------------------------------------------------------
    # Command handlers
    # -----------------------------------------------------------------------

    def handle_uci(self) -> None:
        """
        Respond to the "uci" command.

        The GUI sends "uci" to identify itself and ask the engine for its
        identity and supported options. The engine must reply with id lines
        and a final "uciok". Between those, it may send "option" lines for
        any configurable parameters (none yet in v1).
        """
        _send("id name ChessAI-v1")
        _send("id author Chess AI Project")
        _send("uciok")

    def handle_isready(self) -> None:
        """
        Respond to the "isready" command.

        The GUI sends "isready" to confirm the engine is alive and ready
        to accept "position" and "go" commands. This is also used as a
        synchronization barrier — the GUI waits for "readyok" before
        proceeding. We respond immediately since v1 has no lazy initialization.
        """
        _send("readyok")

    def handle_ucinewgame(self) -> None:
        """
        Respond to the "ucinewgame" command.

        Signals that a new game is starting. We stop any running search,
        reset the board to the starting position, and clear any game-specific
        state (transposition table, killer moves, etc. — none in v1).
        """
        self._stop_search()
        self.board = chess.Board()

    def handle_position(self, tokens: list[str]) -> None:
        """
        Parse and apply a "position" command.

        The "position" command sets the current board state. It can specify
        the starting position or an arbitrary FEN, followed by an optional
        list of moves to replay. This is how the GUI keeps the engine in sync
        with the game being played.

        Command formats:
            position startpos
            position startpos moves e2e4 e7e5 ...
            position fen <FEN>
            position fen <FEN> moves e2e4 e7e5 ...

        Args:
            tokens: The command tokens with "position" already stripped.
                    tokens[0] is "startpos" or "fen".
        """
        try:
            if not tokens:
                return

            if tokens[0] == "startpos":
                self.board = chess.Board()
                move_tokens = tokens[2:] if len(tokens) > 1 and tokens[1] == "moves" else []
            elif tokens[0] == "fen":
                # FEN strings have 6 space-separated fields; find where "moves" appears
                if "moves" in tokens:
                    moves_idx = tokens.index("moves")
                    fen = " ".join(tokens[1:moves_idx])
                    move_tokens = tokens[moves_idx + 1:]
                else:
                    fen = " ".join(tokens[1:])
                    move_tokens = []
                self.board = chess.Board(fen)
            else:
                _log(f"uci: unknown position type: {tokens[0]}")
                return

            # Replay the move list to reach the current position.
            # python-chess handles castling rights, en passant, and repetition
            # detection automatically as moves are pushed.
            for uci_move in move_tokens:
                move = chess.Move.from_uci(uci_move)
                if move in self.board.legal_moves:
                    self.board.push(move)
                else:
                    _log(f"uci: illegal move in position command: {uci_move}")
                    break

        except Exception as e:
            _log(f"uci: error in position command: {e}")

    def handle_go(self, tokens: list[str]) -> None:
        """
        Parse a "go" command and start the search in a background thread.

        The "go" command asks the engine to start searching. It carries time
        control information that the engine uses to decide how long to think.
        We support two modes:
            - movetime <ms>: think for exactly this many milliseconds
            - wtime/btime [winc/binc]: think based on remaining clock time

        After parsing the time budget, we copy the current board state and
        launch a daemon thread to run the search. The main thread continues
        reading stdin so it can handle "stop" immediately.

        Args:
            tokens: The command tokens with "go" already stripped.
        """
        # Stop any previous search that might still be running
        self._stop_search()

        # Parse the time control parameters
        time_limit_ms = self._parse_go_time(tokens)

        # Reset the stop event for the new search
        self.stop_event = threading.Event()

        # Copy the board so the search thread has its own state.
        # The main thread may receive the next "position" command while the
        # search is still running; copying prevents a data race.
        board_copy = self.board.copy()

        # Capture references for the closure
        stop_event = self.stop_event
        time_ms = time_limit_ms

        def search_and_reply() -> None:
            """
            Run the search and emit the UCI info + bestmove lines.

            This closure runs in a daemon thread. When it finishes (either by
            finding a move or being interrupted by stop_event), it sends the
            required "bestmove" response. The GUI will not make its next move
            until it receives this line.
            """
            try:
                start = time.monotonic()
                move, score, depth, nodes = get_best_move(board_copy, time_ms, stop_event)
                elapsed_ms = max(1, int((time.monotonic() - start) * 1000))

                if move is not None:
                    nps = max(1, nodes * 1000 // elapsed_ms)
                    _send(
                        f"info depth {depth} score cp {score} "
                        f"nodes {nodes} nps {nps} time {elapsed_ms}"
                    )
                    _send(f"bestmove {move.uci()}")
                else:
                    # No legal moves: the game is over (checkmate or stalemate).
                    # UCI requires a bestmove response; "(none)" is the standard.
                    _send("bestmove (none)")

            except Exception as e:
                _log(f"search error: {e}")
                _send("bestmove (none)")

        self.search_thread = threading.Thread(target=search_and_reply, daemon=True)
        self.search_thread.start()

    def handle_stop(self) -> None:
        """
        Respond to the "stop" command.

        Signals the search thread to stop and waits for it to finish.
        The search thread will emit a "bestmove" line before exiting.
        """
        self._stop_search()

    def handle_quit(self) -> None:
        """
        Respond to the "quit" command.

        Stop the search and exit the process. We do not send any reply;
        the GUI does not expect one after "quit".
        """
        self._stop_search()
        sys.exit(0)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _stop_search(self) -> None:
        """
        Signal the current search thread to stop and wait for it to exit.

        Sets the stop_event so the search function returns at its next
        check point, then joins the thread with a 2-second timeout. The
        timeout prevents the UCI loop from hanging if the search thread
        misbehaves, but in normal operation the thread exits well within 2s.
        """
        self.stop_event.set()
        if self.search_thread is not None and self.search_thread.is_alive():
            self.search_thread.join(timeout=2.0)
        self.search_thread = None

    def _parse_go_time(self, tokens: list[str]) -> int:
        """
        Extract the time budget in milliseconds from "go" command tokens.

        Supports:
            movetime <ms>       — use exactly this many milliseconds
            wtime <ms> btime <ms> [winc <ms> binc <ms>]
                                — use 1/40 of remaining time + increment

        If neither is found (e.g. "go infinite"), returns a large value
        so the engine searches until "stop" is received.

        Args:
            tokens: The go command tokens (with "go" stripped).

        Returns:
            Time budget in milliseconds.
        """
        params: dict[str, int] = {}
        i = 0
        while i < len(tokens) - 1:
            key = tokens[i]
            try:
                params[key] = int(tokens[i + 1])
                i += 2
            except (ValueError, IndexError):
                i += 1

        # movetime: use exactly the specified duration
        if "movetime" in params:
            return params["movetime"]

        # wtime/btime: allocate based on which colour we are playing
        color = self.board.turn  # chess.WHITE or chess.BLACK
        time_key = "wtime" if color == chess.WHITE else "btime"
        inc_key = "winc" if color == chess.WHITE else "binc"

        if time_key in params:
            time_left = params[time_key]
            increment = params.get(inc_key, 0)
            # Standard formula: allocate 1/40 of remaining time plus increment.
            # This keeps enough time in reserve for the rest of the game.
            return max(1, time_left // 40 + increment)

        # "go infinite" or unrecognised parameters: search until stopped
        return 10_000_000  # ~2.8 hours — effectively infinite


def run_uci_loop() -> None:
    """
    Main UCI protocol loop.

    Reads lines from stdin and dispatches each command to the UciHandler.
    Runs until the "quit" command is received or stdin is closed.

    Error handling:
        Each command is wrapped in a try/except so that a bug in one
        command handler does not crash the engine. Errors are logged to
        stderr and the loop continues. This is important for tournament
        play where crashes lose the game.
    """
    handler = UciHandler()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        tokens = line.split()
        command = tokens[0]
        args = tokens[1:]

        try:
            if command == "uci":
                handler.handle_uci()
            elif command == "isready":
                handler.handle_isready()
            elif command == "ucinewgame":
                handler.handle_ucinewgame()
            elif command == "position":
                handler.handle_position(args)
            elif command == "go":
                handler.handle_go(args)
            elif command == "stop":
                handler.handle_stop()
            elif command == "quit":
                handler.handle_quit()
            else:
                # Unknown commands are silently ignored per the UCI specification.
                # The spec explicitly states engines must ignore unrecognised tokens.
                _log(f"uci: ignoring unknown command: {command!r}")

        except Exception as e:
            _log(f"uci: unhandled error for command {command!r}: {e}")


if __name__ == "__main__":
    run_uci_loop()

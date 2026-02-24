"""
FastAPI web application for the Chess AI engine.

Exposes a single REST endpoint (POST /api/move) that accepts a FEN position
and time limit, runs the engine search, and returns the best move with score
and depth information. Serves the chessboard.js frontend via static files.

Architecture notes:
- Sync endpoint (not async): FastAPI runs sync handlers in a thread pool,
  which is the correct pattern for CPU-bound blocking calls like engine search.
- Static files mounted LAST: route registration is first-match, so API routes
  must be registered before the StaticFiles catch-all.
- Stateless per request: the client sends the full FEN each time; no server-
  side board state is maintained between requests.
"""

import logging
import threading
from pathlib import Path

import chess
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from engine.search import get_best_move

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)

# Absolute path resolved at import time — immune to working-directory changes.
_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Chess AI", version="4.0.0")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class MoveRequest(BaseModel):
    """
    Client request to the engine.

    Fields:
        fen: Full FEN string representing the current board position.
        time_limit: Seconds allocated to the engine for this move (clamped
                    to [0.1, 30.0] to prevent accidental 0-second calls or
                    runaway searches on the free Render tier).
    """

    fen: str
    time_limit: float = 1.0

    @field_validator("time_limit")
    @classmethod
    def clamp_time_limit(cls, v: float) -> float:
        """Clamp time_limit to a safe operating range."""
        return max(0.1, min(v, 30.0))


class MoveResponse(BaseModel):
    """
    Engine response after computing the best move.

    Fields:
        move: Best move in UCI notation (e.g. "e2e4", "e7e8q").
        fen: Board FEN after the engine's move is applied.
        score: Evaluation in centipawns from the engine's perspective.
               Positive = engine is ahead; negative = engine is behind.
        depth: Search depth reached during iterative deepening.
    """

    move: str
    fen: str
    score: int
    depth: int


# ---------------------------------------------------------------------------
# API routes (registered BEFORE StaticFiles mount)
# ---------------------------------------------------------------------------


@app.post("/api/move", response_model=MoveResponse)
def api_move(request: MoveRequest) -> MoveResponse:
    """
    Compute the engine's best move for the given position.

    Validates the FEN, confirms the game is not over, runs iterative-deepening
    search with the requested time budget, applies the move, and returns the
    result.

    Args:
        request: MoveRequest with a FEN string and time limit in seconds.

    Returns:
        MoveResponse with move (UCI), updated FEN, score (cp), and depth.

    Raises:
        HTTPException 400: Malformed FEN or game already over.
        HTTPException 500: Engine returned no move (should not happen in
                           non-terminal positions).
    """
    # --- Parse and validate the FEN ---
    try:
        board = chess.Board(request.fen)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc

    if board.is_game_over():
        reason = board.result()
        raise HTTPException(
            status_code=400,
            detail=f"Game is already over: {reason}",
        )

    # --- Run the engine search ---
    # A fresh stop_event is created per request. The engine self-terminates
    # via TIME_USAGE_FRACTION (90% of the time budget), so we never need to
    # set the event externally here.
    stop_event = threading.Event()
    time_limit_ms = int(request.time_limit * 1000)

    try:
        move, score, depth, nodes = get_best_move(board, time_limit_ms, stop_event)
    except Exception as exc:
        _log.exception("Engine search failed for FEN=%s", request.fen)
        raise HTTPException(status_code=500, detail=f"Engine error: {exc}") from exc

    if move is None:
        raise HTTPException(status_code=500, detail="Engine returned no move")

    _log.info(
        "Move=%s score=%d depth=%d nodes=%d fen=%s",
        move.uci(),
        score,
        depth,
        nodes,
        request.fen[:40],
    )

    # --- Apply the move and return ---
    board.push(move)
    return MoveResponse(
        move=move.uci(),
        fen=board.fen(),
        score=score,
        depth=depth,
    )


@app.get("/", include_in_schema=False)
def serve_root() -> FileResponse:
    """Serve the main chessboard UI."""
    return FileResponse(_STATIC_DIR / "index.html")


# ---------------------------------------------------------------------------
# Static file mount — MUST be last (catch-all for /static/* assets)
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

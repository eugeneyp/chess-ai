# CLAUDE.md — Chess AI Engine Project

> This file provides context for Claude Code (and any AI coding assistant) working on this repository.
> It describes the project, architecture, conventions, and constraints that must be followed.

---

## Project summary

This is a chess AI engine built from scratch in Python as a 5-day learning project. It uses classical search techniques (negamax with alpha-beta pruning, quiescence search, transposition tables) and a hand-crafted evaluation function (material + piece-square tables). The engine is playable via a web interface and testable via the UCI protocol against other engines.

**Target playing strength**: 1200–1800 ELO
**Runtime constraint**: Return a move within 5 seconds on a standard laptop
**Deployment**: Web app on Render.com (FastAPI backend + chessboard.js frontend)

---

## Technology stack

| Component | Technology | Version |
|---|---|---|
| Language | Python | 3.10+ |
| Board logic | `python-chess` | 1.11.2 |
| Web backend | FastAPI + uvicorn | Latest |
| Web frontend | chessboard.js + chess.js | 1.0.0 / 1.0+ |
| Testing | cutechess-cli | Latest |
| Optional speedup | PyPy | 3.10+ |

---

## Project structure

```
chess-ai/
├── CLAUDE.md                  # This file
├── README.md                  # Project documentation
├── requirements.txt           # Python dependencies
├── Procfile                   # Render deployment config
│
├── engine/                    # Core chess AI engine
│   ├── __init__.py
│   ├── evaluate.py            # Evaluation function (material + PSTs)
│   ├── search.py              # Negamax, alpha-beta, quiescence, iterative deepening
│   ├── transposition.py       # Zobrist hashing and transposition table
│   ├── move_ordering.py       # MVV-LVA, killer moves, history heuristic
│   ├── opening_book.py        # Polyglot .bin book reader
│   └── constants.py           # Piece values, PST arrays, search parameters
│
├── interface/                 # Engine communication protocols
│   ├── __init__.py
│   └── uci.py                 # UCI protocol handler (stdin/stdout)
│
├── web/                       # Web application
│   ├── app.py                 # FastAPI application
│   └── static/                # Frontend files
│       ├── index.html         # Main page with chessboard.js
│       ├── main.js            # Game logic, API calls
│       └── style.css          # Styling
│
├── tests/                     # Test suites
│   ├── test_evaluate.py       # Evaluation function tests
│   ├── test_search.py         # Search correctness tests
│   ├── test_uci.py            # UCI protocol tests
│   ├── puzzles/               # Tactical puzzle EPD files
│   │   └── mate_in_2.epd      # Mate-in-2 validation suite
│   └── benchmark.py           # Automated benchmark runner
│
├── books/                     # Opening book files
│   └── gm2001.bin             # Polyglot opening book
│
├── tools/                     # Development utilities
│   ├── run_tournament.sh      # cutechess-cli wrapper
│   ├── run_sprt.sh            # SPRT testing wrapper
│   └── elo_tracker.py         # Log and plot ELO progression
│
└── snapshots/                 # Versioned engine snapshots for benchmarking
    ├── engine_v1.py           # Day 1 snapshot
    ├── engine_v2.py           # Day 2 snapshot
    └── ...
```

---

## Architectural rules

These are non-negotiable decisions. Do not suggest alternatives.

### Board representation and move generation

- **Use `python-chess` for ALL board logic.** Never write a custom move generator, bitboard implementation, or move validation. python-chess handles castling, en passant, pins, promotions, draw detection, and FEN parsing correctly. Custom implementations introduce weeks of debugging.
- Use `chess.Board` as the primary board state object. Pass it by reference to search and evaluation functions.
- Use `board.push(move)` / `board.pop()` for make/unmake during search. Do NOT copy the board.

### Evaluation

- All scores are **centipawn integers** (Pawn = 100). Never use floats for evaluation scores.
- Evaluation is always from **the perspective of the side to move**. The search function handles sign flipping via negamax.
- Piece values: P=100, N=320, B=330, R=500, Q=900, K=20000.
- Use PeSTO piece-square tables (both middlegame and endgame arrays).
- Implement **tapered evaluation**: interpolate between middlegame and endgame PSTs based on a game-phase score calculated from remaining non-pawn material.
- Checkmate returns `+/- 99999` (not infinity). Stalemate returns `0`.
- Mate scores should encode distance to mate: `99999 - ply` so the engine prefers faster mates.

### Search

- **Negamax with alpha-beta pruning** is the core search function.
- **Iterative deepening** wraps the search. Never call a fixed-depth search directly.
- **Time management**: check the clock before each iterative deepening iteration. Hard cutoff at 90% of allocated time. Also check every 2048 nodes (using a node counter) within the search itself.
- **Quiescence search** at depth 0: continue searching captures and promotions until the position is quiet. Include stand-pat evaluation.
- **Move ordering priority** (highest to lowest):
  1. Transposition table best move (if available)
  2. Captures ordered by MVV-LVA (Most Valuable Victim − Least Valuable Aggressor)
  3. Killer moves (2 per ply)
  4. History heuristic (quiet moves that caused beta cutoffs in sibling nodes)
  5. Remaining quiet moves
- **Transposition table**: Zobrist hashing with incremental XOR updates. Store: hash, depth, score, flag (EXACT/LOWERBOUND/UPPERBOUND), best move. Fixed-size dict or array with replacement by depth.
- **Check extensions**: if the side to move is in check, increase search depth by 1 ply.
- **Null-move pruning** (R=3): skip when in check, when the side to move has no pieces (pawns only), or at low depths.

### UCI protocol

- The UCI handler (`interface/uci.py`) must be a standalone script runnable as `python uci.py`.
- It reads from `sys.stdin` and writes to `sys.stdout` with `flush=True` after every output line.
- Required commands: `uci`, `isready`, `ucinewgame`, `position startpos moves ...`, `position fen ... moves ...`, `go movetime <ms>`, `go wtime <ms> btime <ms>`, `stop`, `quit`.
- The engine imports from `engine/` — the UCI wrapper is just a protocol translation layer.
- The `go` command must run the search in a way that `stop` can interrupt it. Use a shared `threading.Event` or periodically check stdin.

### Web application

- **REST API, not WebSockets.** Single endpoint: `POST /api/move`.
- Request body: `{"fen": "<FEN string>", "time_limit": <seconds as float>}`
- Response body: `{"move": "<UCI string>", "fen": "<new FEN>", "score": <centipawns int>, "depth": <int>}`
- The engine is imported directly into the FastAPI process — no subprocess spawning for the web app.
- Frontend sends the full FEN after each move. The backend is stateless per request (no server-side board state).
- `chess.js` validates moves client-side before sending. Invalid moves never reach the backend.
- Serve static files from `web/static/` via FastAPI's `StaticFiles` mount.

---

## Code style and conventions

### General principles

- **Human readability is the top priority.** This is a learning project. Every function, class, and algorithm should be understandable by a developer studying chess AI for the first time.
- **Explain the chess programming concepts.** Docstrings should explain not just what a function does, but WHY — what chess programming problem it solves and how it relates to the overall engine architecture.
- Write code that reads like a textbook implementation of each algorithm.

### Python style

- Follow **PEP 8** with a maximum line length of **100 characters**.
- Use **type hints** on all function signatures and return types.
- Use **f-strings** for string formatting.
- Prefer **explicit imports** over wildcard imports (`from chess import Board, Move` not `from chess import *`).
- Use **constants** for magic numbers. Define piece values, search parameters, and table sizes in `constants.py`.
- Use `snake_case` for functions and variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.

### Documentation standards

Every module, class, and public function must have a docstring. Follow this format:

```python
def negamax(
    board: chess.Board,
    depth: int,
    alpha: int,
    beta: int,
    ply: int,
    search_state: SearchState,
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
        depth: Remaining search depth in plies. At depth 0, drops into
               quiescence search.
        alpha: Lower bound of the search window (best score we can guarantee).
        beta: Upper bound of the search window (best score opponent allows).
        ply: Distance from the root position (0 at root). Used for mate
             distance scoring and killer move indexing.
        search_state: Shared mutable state (TT, killers, history, node count,
                      time control).

    Returns:
        The evaluation score in centipawns from the perspective of the side
        to move. Positive means the side to move is ahead.

    Chess programming context:
        Alpha-beta pruning reduces the search tree from O(b^d) to approximately
        O(b^(d/2)) with perfect move ordering, where b is the branching factor
        (~35 in chess) and d is the search depth. This means a depth-6 search
        examines roughly as many nodes as a depth-3 search without pruning.
    """
```

### Inline comments

Use inline comments to explain chess-specific logic and algorithmic decisions:

```python
# Stand-pat score: if the static evaluation already exceeds beta,
# the side to move is doing so well that searching captures can only
# make things better — the opponent would never allow this position.
stand_pat = evaluate(board)
if stand_pat >= beta:
    return beta
```

### File-level module docstrings

Each module should begin with a docstring explaining its role in the engine:

```python
"""
Quiescence search: resolving tactical instability at leaf nodes.

The "horizon effect" occurs when a fixed-depth search evaluates a position
in the middle of a piece exchange. For example, at depth 4, the engine might
see that it captures a knight but not that the opponent recaptures its queen
on move 5. Quiescence search fixes this by continuing to search captures
and promotions beyond the nominal depth until the position is "quiet."

This module implements:
- quiescence(): The recursive capture-only search
- is_quiet(): Determines if a position has no hanging tactical threats
- delta_pruning(): Skips captures that can't possibly raise alpha
"""
```

### Error handling

- The engine must never crash during a game. Catch exceptions in the UCI loop and the web API.
- If the search times out, return the best move found so far (iterative deepening guarantees this).
- If the opening book lookup fails, fall back silently to engine search.
- Log errors to stderr (UCI) or Python logging (web app). Never print debug output to stdout in UCI mode — it corrupts the protocol.

### Testing

- Every search enhancement must be validated via SPRT before moving on.
- Keep engine snapshots (`snapshots/engine_v1.py`, etc.) for regression testing.
- Mate-in-2 puzzle suite is the smoke test for search correctness.
- Unit tests for evaluation: known positions should return expected centipawn ranges.
- Unit tests for UCI: verify correct responses to standard command sequences.

---

## Performance constraints and guidelines

- **Target: 5,000–15,000 NPS on CPython**, 20,000–40,000 on PyPy.
- At these speeds, expect **depth 3–4 + quiescence** within 5 seconds for complex middlegame positions.
- **Do not prematurely optimize.** Algorithmic improvements (better pruning, move ordering) provide far more ELO than micro-optimizations. A 10% speed gain adds ~15 ELO. Adding quiescence search adds ~200+ ELO.
- **Do not use numpy, cython, or numba** in Phase 1. They add complexity without enough benefit at this ELO range. PyPy compatibility is more valuable.
- **Avoid object creation in hot loops.** In the search function, avoid creating lists, dicts, or objects per node. Reuse data structures where possible.
- **Move ordering is the highest-leverage performance optimization.** Good ordering makes alpha-beta prune more aggressively, effectively doubling search depth for free.

---

## Common pitfalls to avoid

1. **Never write a custom move generator.** Use python-chess. This saves weeks of debugging.
2. **Never evaluate non-quiet positions at leaf nodes.** Always drop into quiescence search at depth 0.
3. **Never use floats for evaluation scores.** Centipawn integers only. Float comparison bugs silently corrupt alpha-beta.
4. **Never print to stdout in UCI mode** except for valid UCI responses. Debug output goes to stderr.
5. **Never call a fixed-depth search directly.** Always use iterative deepening with time management.
6. **Never skip draw detection.** Check `board.is_game_over()`, `board.is_repetition()`, `board.is_fifty_moves()` at the top of the search function. Return 0 for draws.
7. **Never test only by playing manually.** Use cutechess-cli with SPRT for statistically valid measurements.
8. **Never add a feature without SPRT validation.** If ELO doesn't improve after adding a feature, the implementation likely has a bug.
9. **Never store the full board in the transposition table.** Store only the Zobrist hash (risk of collision is negligible at 64 bits).
10. **Never forget to handle mate distance.** Score mates as `99999 - ply` so the engine prefers checkmate in 2 over checkmate in 5.

---

## Implementation priority (effort-to-ELO ratio)

When deciding what to work on next, consult this ranked list. Features at the top provide the most ELO gain per hour of implementation effort:

| Priority | Feature | Est. ELO gain | Est. hours |
|---|---|---|---|
| 1 | Alpha-beta pruning | +300–500 | 1–2 |
| 2 | Piece-square tables (PeSTO) | +200–400 | 2–3 |
| 3 | Quiescence search | +200–400 | 3–5 |
| 4 | MVV-LVA move ordering | +100–200 | 1–2 |
| 5 | Iterative deepening + time mgmt | +50–100 | 2–3 |
| 6 | Transposition table (Zobrist) | +130–160 | 4–6 |
| 7 | Killer move heuristic | +50–80 | 1–2 |
| 8 | Check extensions | +30–50 | 0.5–1 |
| 9 | Null-move pruning | +50–100 | 2–3 |
| 10 | Tapered evaluation | +50–100 | 2–3 |
| 11 | Opening book (Polyglot) | +30–80 | 0.5–1 |
| 12 | Late move reductions | +100–200 | 3–5 |
| 13 | History heuristic | +30–50 | 1–2 |
| 14 | PyPy runtime | +~250 | 0 (just change interpreter) |

---

## Glossary of chess programming terms

For Claude Code's reference when reading and writing code:

- **Alpha-beta pruning**: Optimization of minimax that eliminates branches which cannot affect the final decision.
- **Centipawn (cp)**: 1/100th of a pawn's value. Standard unit for evaluation scores.
- **FEN (Forsyth-Edwards Notation)**: String encoding of a complete chess position.
- **Killer move**: A quiet (non-capture) move that caused a beta cutoff at the same ply in a sibling node. Likely good in similar positions.
- **MVV-LVA**: Move ordering heuristic: prioritize capturing high-value pieces with low-value pieces.
- **Negamax**: Simplification of minimax exploiting the zero-sum property. Always maximizes; negates child scores.
- **NPS (Nodes Per Second)**: Primary speed metric for chess engines.
- **Ply**: A half-move (one player's turn). Depth 4 = 4 plies = 2 full moves by each side.
- **PST (Piece-Square Table)**: 8×8 array of positional bonuses for each piece type. Knights get bonuses for central squares; kings get bonuses for castled positions.
- **Quiescence search**: Capture-only search at leaf nodes to resolve tactical instability.
- **Stand-pat**: In quiescence search, the option to "do nothing" — the static evaluation serves as a lower bound.
- **Tapered evaluation**: Blending middlegame and endgame evaluation weights based on remaining material.
- **Transposition table (TT)**: Hash table caching previously searched positions to avoid redundant work.
- **UCI (Universal Chess Interface)**: Text-based protocol for chess engine communication.
- **Zobrist hashing**: Incremental position hashing using XOR of random keys for each piece-square combination.

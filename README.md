# Chess AI

A chess engine built from scratch in Python as a 5-day learning project. It implements
classical search techniques used by real chess engines — negamax with alpha-beta pruning,
quiescence search, MVV-LVA move ordering, and tapered PeSTO evaluation — and is playable
via a web interface or the UCI protocol against other engines.

**Playing strength: ~1580–1640 ELO** (measured vs Stockfish with `UCI_LimitStrength`)

---

## Table of contents

- [Purpose](#purpose)
- [Architecture](#architecture)
- [AI techniques](#ai-techniques)
- [Project structure](#project-structure)
- [Local development](#local-development)
- [Deployment (Render.com)](#deployment-rendercom)
- [Benchmarking with fastchess](#benchmarking-with-fastchess)
- [Benchmark results](#benchmark-results)
- [Roadmap](#roadmap)

---

## Purpose

This project exists to learn chess programming from first principles. Each step of the
engine's development introduced a new technique from the chess programming literature,
with an immediate ELO measurement after each addition to quantify its effect.

The constraint is deliberate: return a move within 5 seconds on a standard laptop, using
only CPython and `python-chess`. No C extensions, no bitboards, no neural networks.

---

## Architecture

```
chess-ai/
├── engine/               # Core chess AI engine
│   ├── constants.py      # Piece values, PST arrays, search parameters
│   ├── evaluate.py       # Tapered PeSTO evaluation (material + piece-square tables)
│   ├── search.py         # Negamax, alpha-beta, quiescence, iterative deepening
│   ├── transposition.py  # Zobrist hashing and transposition table
│   ├── move_ordering.py  # MVV-LVA, killer moves, history heuristic
│   └── opening_book.py   # Polyglot .bin book reader
│
├── interface/
│   └── uci.py            # UCI protocol handler (stdin/stdout, threading)
│
├── web/
│   ├── app.py            # FastAPI application (POST /api/move)
│   └── static/           # Frontend: chessboard.js + chess.js
│
├── snapshots/            # Frozen self-contained engine versions for benchmarking
│   ├── engine_v1.py      # Random mover
│   ├── engine_v2.py      # Negamax depth 3 + material eval
│   ├── engine_v3.py      # + Alpha-beta pruning
│   └── engine_v4.py      # + PeSTO + quiescence + MVV-LVA + iterative deepening
│
├── tools/
│   ├── run_tournament.sh # fastchess wrapper (self-play, vs Stockfish, SPRT)
│   └── elo_tracker.py    # Log and plot ELO progression
│
└── tests/
    ├── test_evaluate.py
    ├── test_search.py
    ├── test_uci.py
    └── puzzles/mate_in_2.epd
```

### Key design decisions

- **`python-chess` for all board logic.** Move generation, castling, en passant, pins,
  draw detection, and FEN parsing are all handled by `python-chess`. Custom move
  generators introduce weeks of debugging for marginal gain at this ELO range.

- **`board.push()` / `board.pop()` for make/unmake.** The board is modified in-place
  during search and restored on return. No board copying.

- **Stateless REST API.** The client sends the full FEN with every request. The server
  holds no game state between requests, making the backend trivially scalable and the
  frontend the single source of truth.

- **Centipawn integers only.** Evaluation scores are always integers (1 pawn = 100).
  Float comparison bugs silently corrupt alpha-beta windows.

---

## AI techniques

### v1 — Random mover (baseline)

Selects a uniformly random legal move. Zero chess understanding; exists only as a
benchmark baseline. ELO: ~800 (estimated).

### v2 — Negamax + material evaluation

**Negamax** is a simplification of minimax that exploits the zero-sum property of chess:
one player's gain is exactly the other player's loss. Instead of alternating between
maximizing and minimizing, negamax always maximizes but negates the score returned by
recursive calls.

**Material evaluation**: piece values in centipawns — P=100, N=320, B=330, R=500, Q=900.
The score is the sum of White's material minus Black's material, negated for Black's turn.

Searched to fixed depth 3. ELO gain over v1: **+436 ELO** (17W 0L 3D in 20 games).

### v3 — Alpha-beta pruning

**Alpha-beta pruning** eliminates branches that cannot influence the final decision.
The search maintains a window `[alpha, beta]`:
- If a position scores `>= beta`, the opponent has a refutation — prune immediately (beta cutoff).
- If a position scores `> alpha`, we raise alpha (we found a better move).

With perfect move ordering, alpha-beta reduces the search tree from O(b^d) to O(b^(d/2)),
where `b ≈ 35` (average branching factor in chess) and `d` is depth. This means a
depth-6 search examines roughly as many nodes as a depth-3 search without pruning.

Node reduction at depth 3: **9.5×** fewer nodes than v2 (2,149 avg vs 20,421 avg).

### v4 — PeSTO + quiescence + MVV-LVA + iterative deepening

This step added four improvements simultaneously:

**PeSTO piece-square tables (PSTs):** Each piece type has an 8×8 table of positional
bonuses. Knights score higher near the center; kings score higher near the corner in
the middlegame. PeSTO provides separate middlegame and endgame tables.

**Tapered evaluation:** Instead of switching abruptly between PST sets, the evaluation
blends them based on remaining non-pawn material. A full board is 100% middlegame;
K+P vs K is 100% endgame. This eliminates the discontinuity at the phase boundary.

**Quiescence search:** At depth 0, instead of returning a static evaluation, the engine
continues searching captures until the position is "quiet." This eliminates the
*horizon effect* — e.g., without quiescence, the engine evaluates mid-exchange and
thinks it won a piece, missing the recapture on the next move.

Stand-pat: the side to move can choose *not* to capture. The static evaluation is a
lower bound — if it already exceeds beta, prune immediately.

**MVV-LVA (Most Valuable Victim − Least Valuable Aggressor):** Captures are sorted so
that `PxQ` is searched before `QxP`. High-value captures tend to raise alpha quickly,
causing earlier beta cutoffs. The score formula is:

```
captures: 10,000 + victim_value − attacker_value
quiet moves: 0
```

**Iterative deepening:** The engine searches depth 1, 2, 3, ... until the time budget
is consumed. Each completed iteration provides a valid fallback move if the next
iteration is interrupted. The engine also checks elapsed time every 2,048 nodes (inside
both `negamax()` and `quiescence()`) to hard-stop at 90% of the allocated budget.

Combined ELO gain over v3: **+800 ELO**. Search depth at 5 seconds: 4–7 plies (vs
fixed depth 3 in 148ms for v3).

### Mate scoring

Checkmate returns `99,999 − ply` rather than a fixed constant. This encodes the distance
to mate: a forced mate in 1 scores 99,998, a mate in 3 scores 99,996. The engine always
plays the fastest available checkmate.

---

## Local development

### Prerequisites

- Python 3.10+
- Stockfish (for benchmarking): `brew install stockfish`
- fastchess v1.8.0-alpha binary at `tools/fastchess` (macOS x86-64)
  — download from https://github.com/Disservin/fastchess/releases

### Setup

```bash
python3 -m venv /tmp/chess-venv
/tmp/chess-venv/bin/pip install -r requirements.txt
```

> Note: `requirements.txt` uses `chess==1.11.2` (not `python-chess`). The PyPI package
> name changed; the real package installs as `chess`.

### Run the web app

```bash
/tmp/chess-venv/bin/python -m uvicorn web.app:app --reload --port 8000
```

Open http://localhost:8000. You play White; the engine plays Black.

### Run the UCI engine directly

```bash
PYTHONPATH=. /tmp/chess-venv/bin/python3 interface/uci.py
```

Then type UCI commands manually, for example:

```
uci
isready
position startpos moves e2e4
go movetime 3000
```

### Run tests

```bash
/tmp/chess-venv/bin/python -m pytest tests/
```

---

## Deployment (Render.com)

The app deploys automatically on push to `main`. Render detects the `Procfile` and runs:

```
web: uvicorn web.app:app --host 0.0.0.0 --port $PORT
```

Dependencies are installed from `requirements.txt`. No build step is required.

Render typically takes 2–5 minutes to deploy after a push (polls GitHub every ~30–60s,
then builds). Monitor the deploy status in the Render dashboard.

**Free tier note:** The free Render instance sleeps after 15 minutes of inactivity. The
first request after waking takes ~30 seconds (cold start). Time limit per request is
clamped to 30 seconds in `web/app.py` to prevent runaway CPU on the free tier.

---

## Benchmarking with fastchess

[fastchess](https://github.com/Disservin/fastchess) is a modern engine testing tool
that runs automated tournaments and computes ELO estimates. The wrapper script
`tools/run_tournament.sh` handles all modes.

### Prerequisites

```bash
# macOS fd limit — required before running fastchess
ulimit -n 65536

# PYTHONPATH must include the repo root for engine imports
export PYTHONPATH=/path/to/chess-ai
```

### Modes

**Self-play** (smoke test — verifies engine runs without crashes):
```bash
./tools/run_tournament.sh self
```

**v2 vs v1** (validates that negamax beats random play):
```bash
./tools/run_tournament.sh v2_vs_v1
```

**vs Stockfish** (measures absolute ELO; default: SF-1320, 20 games):
```bash
./tools/run_tournament.sh stockfish           # vs SF-1320, 20 games
./tools/run_tournament.sh stockfish 1500      # vs SF-1500, 20 games
./tools/run_tournament.sh stockfish 1500 50   # vs SF-1500, 100 games
```

**SPRT** (statistically rigorous comparison between two versions):
```bash
./tools/run_tournament.sh sprt
```
SPRT stops as soon as the result is statistically significant (α=0.05, β=0.05),
using fewer games than a fixed-game tournament.

### ELO estimate formula

When running against Stockfish at a known ELO, estimate absolute strength via:

```
ELO ≈ SF_ELO − 400 × log10((1 − score%) / score%)
```

Examples vs SF-1320:
| Score% | Estimated ELO |
|--------|---------------|
| 5%     | ~808          |
| 10%    | ~939          |
| 20%    | ~1040         |
| 50%    | 1320 (equal)  |
| 70%    | ~1509         |
| 80%    | ~1621         |

### Time control notes

- **Never use `st=N` (per-move time) for Stockfish** with `UCI_LimitStrength`. Stockfish
  overshoots per-move limits by ~1ms, causing time forfeit losses. Use game-time
  `tc=15+0.1` instead; `-recover` handles the occasional overshoot.
- `tc=10+0.1` was too tight for Python engines due to ~1s startup overhead; `tc=15+0.1`
  is the minimum safe game-time control.
- PGN files are saved to `results/` with timestamps so successive runs don't overwrite
  each other.

---

## Benchmark results

All tests run on a MacBook (CPython 3.12, x86-64). Time control: `tc=15+0.1` unless noted.

### Step-by-step ELO progression

| Version | Technique added | ELO (approx) | Notes |
|---------|----------------|--------------|-------|
| v1 | Random mover | ~800 | Baseline |
| v2 | Negamax depth 3 + material eval | ~1236 | +436 ELO |
| v3 | Alpha-beta pruning | ~768 | Regression: depth-3 too shallow at tc=15+0.1 |
| v4 | PeSTO + quiescence + MVV-LVA + iterative deepening | **~1580–1640** | +800 ELO vs v3 |

> v3 regression note: v3's ELO was measured vs Stockfish-1320 at `tc=15+0.1`. v3 runs
> at fixed depth 3 (~148ms/move), leaving 14+ seconds unused each turn. The engine
> is simply too shallow for this time control. v2's measurement used `st=10` (10s/move),
> giving it more time to play its fixed-depth search.

### v2 node statistics (depth 3, go movetime 60s)

| Metric | Value |
|--------|-------|
| Avg nodes/move | 20,421 |
| Avg NPS | 17,030 |
| Avg time | 1,357ms |
| Slowest position | 62,795 nodes (4,002ms) |

### v3 node statistics (depth 3, alpha-beta)

| Metric | Value |
|--------|-------|
| Avg nodes/move | 2,149 |
| Avg NPS | 13,710 |
| Avg time | 148ms |
| Node reduction vs v2 | **9.5×** |

### v4 node statistics (iterative deepening, 5s budget)

| Metric | Value |
|--------|-------|
| Depth reached | 4–7 plies |
| Avg nodes/move | ~61,030 |
| Avg time | ~4,732ms |

### v4 vs Stockfish results

**vs Stockfish-1320** (50 games, tc=15+0.1):
- 41 clean games (9 Stockfish time forfeits excluded): **33W 7L 1D (81.7%)**
- Estimated ELO: **~1580**
- v4 timeouts: 0

**vs Stockfish-1500** (100 games, tc=60+1):
- **65W 27L 8D (69.0%)**
- Estimated ELO: **~1639**
- v4 timeouts: 0 | Stockfish timeouts: 0
- Avg search depth: 3.4 plies | Max depth: 6

### v2 vs v1 tournament (20 games, st=10)

- **17W 0L 3D** for v2 (+436 ELO, nElo +911)
- All 3 draws: threefold repetition (v2 doesn't yet avoid repetition)
- v2 never lost

---

## Roadmap

Features are prioritized by ELO gain per implementation hour:

| Priority | Feature | Est. ELO gain |
|----------|---------|---------------|
| Next | Transposition table (Zobrist hashing) | +130–160 |
| | Killer move heuristic | +50–80 |
| | Null-move pruning (R=3) | +50–100 |
| | Late move reductions (LMR) | +100–200 |
| | Opening book (Polyglot) | +30–80 |
| | History heuristic | +30–50 |
| | PyPy runtime | +~250 (0 code changes) |

---

## Tech stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| Board logic | `chess==1.11.2` (python-chess) |
| Web backend | FastAPI + uvicorn |
| Web frontend | chessboard.js 1.0.0 + chess.js 0.10.2 |
| Engine testing | fastchess v1.8.0-alpha |
| Deployment | Render.com |

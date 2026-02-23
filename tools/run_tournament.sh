#!/usr/bin/env bash
# run_tournament.sh — fastchess benchmark wrapper
#
# Runs automated tournaments to measure engine strength.
# Uses fastchess (tools/fastchess) — a modern cutechess-cli alternative.
# Binary is at tools/fastchess (macOS x86-64, v1.8.0-alpha, not committed to git).
# Download: https://github.com/Disservin/fastchess/releases
#
# Usage:
#   ./tools/run_tournament.sh              # self-play (default)
#   ./tools/run_tournament.sh stockfish    # vs Stockfish at ELO 1000
#   ./tools/run_tournament.sh sprt        # SPRT test against previous version
#
# The results directory is created automatically. PGN files are named with
# the current date-time so successive runs don't overwrite each other.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${REPO_ROOT}/results"
FASTCHESS="${REPO_ROOT}/tools/fastchess"
PYTHON="/tmp/chess-venv/bin/python3"
ENGINE_SCRIPT="${REPO_ROOT}/interface/uci.py"
ENGINE_NAME="ChessAI-v3"

# Snapshot scripts (self-contained, no engine/ imports)
ENGINE_V1="${REPO_ROOT}/snapshots/engine_v1.py"
ENGINE_V2="${REPO_ROOT}/snapshots/engine_v2.py"
ENGINE_V3="${REPO_ROOT}/snapshots/engine_v3.py"

# Time control: 10 seconds + 0.1 second increment per move.
# This is fast enough for 100 games to complete in ~30 minutes while
# giving the engine enough time to think at low depth.
TIME_CONTROL="10+0.1"
ROUNDS=50  # fastchess -rounds plays each pairing N times; 50 rounds * 2 games = 100 games

# Create results directory if it doesn't exist
mkdir -p "${RESULTS_DIR}"

# Timestamp for unique output filenames
TS="$(date +%Y%m%d_%H%M%S)"

# ---------------------------------------------------------------------------
# PYTHONPATH must include the repo root so `import engine` works inside the
# engine subprocess launched by fastchess.
# ---------------------------------------------------------------------------
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

# fastchess requires enough file descriptors for engine subprocesses.
# macOS defaults to 256; raise it to avoid "not enough file descriptors" errors.
ulimit -n 65536 2>/dev/null || true

# ---------------------------------------------------------------------------
# Verify fastchess is present
# ---------------------------------------------------------------------------
if [[ ! -x "${FASTCHESS}" ]]; then
    echo "Error: fastchess not found at ${FASTCHESS}"
    echo "Download from: https://github.com/Disservin/fastchess/releases"
    echo "Then: cp fastchess ${FASTCHESS} && chmod +x ${FASTCHESS}"
    exit 1
fi

# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------
MODE="${1:-self}"

case "${MODE}" in

  v2_vs_v1)
    # -----------------------------------------------------------------------
    # Benchmark v2 (negamax depth 3) vs v1 (random mover).
    # Both engines are standalone snapshot scripts — frozen, self-contained.
    # A strong v2 win rate confirms negamax + material eval beats random play.
    # Expected: v2 wins >90% of games (any search beats a random mover).
    #
    # Time control: 10 seconds per move (not per game). This ensures v2 gets
    # enough time to complete the depth-3 search (~8-9 seconds on CPython)
    # rather than timing out mid-search. v1 (random mover) is instantaneous.
    # Fewer rounds (10) since each game takes longer at st=10.
    # -----------------------------------------------------------------------
    V2_ROUNDS=10
    echo "Starting v2 vs v1 benchmark (${V2_ROUNDS} rounds x 2 games, st=10)..."
    PGN="${RESULTS_DIR}/v2_vs_v1_${TS}.pgn"

    "${FASTCHESS}" \
      -engine cmd="${PYTHON}" args="${ENGINE_V2}" name="ChessAI-v2" proto=uci \
      -engine cmd="${PYTHON}" args="${ENGINE_V1}" name="ChessAI-v1" proto=uci \
      -each st=10 \
      -rounds "${V2_ROUNDS}" \
      -repeat \
      -recover \
      -pgnout "file=${PGN}"

    echo "Done. PGN saved to: ${PGN}"
    ;;

  self)
    # -----------------------------------------------------------------------
    # Self-play: engine plays itself to verify it runs without crashes.
    # Expected result: ~50% wins for each side (random mover = equal strength).
    # Slight White advantage is normal due to first-mover advantage.
    # -----------------------------------------------------------------------
    echo "Starting self-play tournament (${ROUNDS} rounds x 2 games, tc=${TIME_CONTROL})..."
    PGN="${RESULTS_DIR}/self_play_${TS}.pgn"

    "${FASTCHESS}" \
      -engine cmd="${PYTHON}" args="${ENGINE_SCRIPT}" name="${ENGINE_NAME}-White" proto=uci \
      -engine cmd="${PYTHON}" args="${ENGINE_SCRIPT}" name="${ENGINE_NAME}-Black" proto=uci \
      -each tc="${TIME_CONTROL}" \
      -rounds "${ROUNDS}" \
      -repeat \
      -recover \
      -pgnout "file=${PGN}"

    echo "Done. PGN saved to: ${PGN}"
    ;;

  stockfish)
    # -----------------------------------------------------------------------
    # Benchmark the current engine snapshot vs Stockfish at a known ELO.
    # Measures absolute engine strength via score% → ELO formula.
    #
    # Stockfish minimum UCI_Elo is 1320 (range: 1320-3190).
    # Arguments (all optional):
    #   $2 = Stockfish ELO (default 1320)
    #   $3 = Number of rounds (default 10 → 20 games; use 1 for a single game)
    # Examples:
    #   ./tools/run_tournament.sh stockfish          # 20 games vs SF1320
    #   ./tools/run_tournament.sh stockfish 1320 1   # 1 game vs SF1320 (verification)
    #   ./tools/run_tournament.sh stockfish 1500     # 20 games vs SF1500
    #
    # ELO estimate formula:
    #   Elo ≈ SF_Elo − 400 × log10((1 − score%) / score%)
    #   5%  score vs 1320 → ~808 ELO
    #   10% score vs 1320 → ~939 ELO
    #   20% score vs 1320 → ~1040 ELO
    #   50% score vs 1320 → 1320 ELO (equal strength)
    #
    # Time control: tc=15+0.1 (15 seconds per game + 0.1s increment).
    # Stockfish's UCI_LimitStrength mode must use game-time (tc), not per-move
    # (st=N), because it consistently overshoots per-move limits by ~1ms,
    # causing spurious time-forfeit losses. tc=10+0.1 was too tight for v3
    # (Python startup overhead ~1s). tc=15+0.1 keeps games to ~28s each;
    # Stockfish occasionally overshoots (~1/6 games) but -recover handles it.
    # -----------------------------------------------------------------------
    if ! command -v stockfish &>/dev/null; then
        echo "Error: stockfish not found on PATH. Install with: brew install stockfish"
        exit 1
    fi

    SF_ELO="${2:-1320}"
    SF_ROUNDS="${3:-10}"

    # For a single-game run (rounds=1) play only one color pairing.
    # For multi-round runs, use -repeat to play both colors per round.
    if [[ "${SF_ROUNDS}" -eq 1 ]]; then
        REPEAT_FLAG="-games 1"
        GAME_DESC="1 game"
    else
        REPEAT_FLAG="-repeat"
        GAME_DESC="${SF_ROUNDS} rounds x 2 games"
    fi

    echo "Starting ChessAI vs Stockfish-${SF_ELO} (${GAME_DESC}, tc=15+0.1)..."
    PGN="${RESULTS_DIR}/vs_sf${SF_ELO}_${TS}.pgn"

    "${FASTCHESS}" \
      -engine cmd="${PYTHON}" args="${ENGINE_SCRIPT}" name="${ENGINE_NAME}" proto=uci \
      -engine cmd="stockfish" name="Stockfish-${SF_ELO}" proto=uci \
        option.UCI_LimitStrength=true \
        option.UCI_Elo="${SF_ELO}" \
      -each tc=15+0.1 \
      -rounds "${SF_ROUNDS}" \
      ${REPEAT_FLAG} \
      -recover \
      -pgnout "file=${PGN}"

    echo "Done. PGN saved to: ${PGN}"
    echo ""
    echo "ELO estimate formula:"
    echo "  Elo ≈ ${SF_ELO} - 400 * log10((1 - score%) / score%)"
    echo "  e.g. 5% → ~808, 10% → ~939, 20% → ~1040, 50% → ${SF_ELO}"
    ;;

  sprt)
    # -----------------------------------------------------------------------
    # SPRT (Sequential Probability Ratio Test): statistically rigorous ELO
    # comparison between two engine versions.
    #
    # SPRT stops as soon as one hypothesis is accepted or rejected, so
    # it uses fewer games than a fixed-game tournament while giving the same
    # statistical confidence.
    #
    # H0: new engine is no stronger than baseline (ELO delta <= 0)
    # H1: new engine is stronger by at least 10 ELO
    # Alpha (false positive) = 0.05, Beta (false negative) = 0.05
    #
    # Usage: Edit ENGINE_CMD_NEW below to point to the new version.
    # -----------------------------------------------------------------------
    ENGINE_CMD_NEW="${ENGINE_SCRIPT}"  # TODO: point to new version's script when testing
    echo "Starting SPRT test (stopping when result is statistically significant)..."
    PGN="${RESULTS_DIR}/sprt_${TS}.pgn"

    "${FASTCHESS}" \
      -engine cmd="${PYTHON}" args="${ENGINE_CMD_NEW}" name="${ENGINE_NAME}-New" proto=uci \
      -engine cmd="${PYTHON}" args="${ENGINE_SCRIPT}" name="${ENGINE_NAME}-Base" proto=uci \
      -each tc="${TIME_CONTROL}" \
      -sprt elo0=0 elo1=10 alpha=0.05 beta=0.05 \
      -rounds 500 \
      -repeat \
      -recover \
      -pgnout "file=${PGN}"

    echo "Done. PGN saved to: ${PGN}"
    ;;

  *)
    echo "Usage: $0 [v2_vs_v1|self|stockfish|sprt]"
    exit 1
    ;;
esac

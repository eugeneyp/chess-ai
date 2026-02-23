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
ENGINE_NAME="ChessAI-v1"

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
    # vs Stockfish limited to ELO 1000.
    # Measures approximate engine strength. A random mover (~0 ELO) will lose
    # nearly all games against a 1320 ELO engine.
    # After adding alpha-beta + eval, aim for >5% wins vs Stockfish 1320.
    # Note: Stockfish 18 minimum UCI_Elo is 1320 (range: 1320-3190).
    # -----------------------------------------------------------------------
    if ! command -v stockfish &>/dev/null; then
        echo "Error: stockfish not found on PATH. Install with: brew install stockfish"
        exit 1
    fi

    echo "Starting tournament vs Stockfish ELO 1000 (${ROUNDS} rounds, tc=${TIME_CONTROL})..."
    PGN="${RESULTS_DIR}/vs_sf1000_${TS}.pgn"

    "${FASTCHESS}" \
      -engine cmd="${PYTHON}" args="${ENGINE_SCRIPT}" name="${ENGINE_NAME}" proto=uci \
      -engine cmd="stockfish" name="Stockfish-1320" proto=uci \
        option.UCI_LimitStrength=true \
        option.UCI_Elo=1320 \
      -each tc="${TIME_CONTROL}" \
      -rounds "${ROUNDS}" \
      -repeat \
      -recover \
      -pgnout "file=${PGN}"

    echo "Done. PGN saved to: ${PGN}"
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
    echo "Usage: $0 [self|stockfish|sprt]"
    exit 1
    ;;
esac

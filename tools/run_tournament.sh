#!/usr/bin/env bash
# run_tournament.sh — cutechess-cli benchmark wrapper
#
# Runs automated tournaments to measure engine strength.
# Requires cutechess-cli to be installed and on PATH.
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
ENGINE_CMD="python3 ${REPO_ROOT}/interface/uci.py"
ENGINE_NAME="ChessAI-v1"

# Time control: 10 seconds + 0.1 second increment per move.
# This is fast enough for 100 games to complete in ~30 minutes while
# giving the engine enough time to think at low depth.
TIME_CONTROL="10+0.1"
GAMES=100

# Create results directory if it doesn't exist
mkdir -p "${RESULTS_DIR}"

# Timestamp for unique output filenames
TS="$(date +%Y%m%d_%H%M%S)"

# ---------------------------------------------------------------------------
# PYTHONPATH must include the repo root so `import engine` works inside the
# engine subprocess launched by cutechess-cli.
# ---------------------------------------------------------------------------
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

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
    echo "Starting self-play tournament (${GAMES} games, tc=${TIME_CONTROL})..."
    PGN="${RESULTS_DIR}/self_play_${TS}.pgn"

    cutechess-cli \
      -engine cmd="${ENGINE_CMD}" name="${ENGINE_NAME}-White" proto=uci \
      -engine cmd="${ENGINE_CMD}" name="${ENGINE_NAME}-Black" proto=uci \
      -each tc="${TIME_CONTROL}" \
      -games "${GAMES}" \
      -pgnout "${PGN}" \
      -repeat \
      -recover \
      -debug

    echo "Done. PGN saved to: ${PGN}"
    ;;

  stockfish)
    # -----------------------------------------------------------------------
    # vs Stockfish limited to ELO 1000.
    # Measures approximate engine strength. A random mover (~0 ELO) will lose
    # nearly all games against a 1000 ELO engine.
    # After adding alpha-beta + eval, aim for >5% wins vs Stockfish 1000.
    # -----------------------------------------------------------------------
    echo "Starting tournament vs Stockfish ELO 1000 (${GAMES} games, tc=${TIME_CONTROL})..."
    PGN="${RESULTS_DIR}/vs_sf1000_${TS}.pgn"

    cutechess-cli \
      -engine cmd="${ENGINE_CMD}" name="${ENGINE_NAME}" proto=uci \
      -engine cmd="stockfish" name="Stockfish-1000" proto=uci \
        option.UCI_LimitStrength=true \
        option.UCI_Elo=1000 \
      -each tc="${TIME_CONTROL}" \
      -games "${GAMES}" \
      -pgnout "${PGN}" \
      -repeat \
      -recover \
      -debug

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
    # H0: new engine is ≥5 ELO weaker (change is bad)
    # H1: new engine is ≥5 ELO stronger (change is good)
    # Alpha (false positive) = 0.05, Beta (false negative) = 0.05
    #
    # Usage: Edit ENGINE_CMD_NEW below to point to the new version.
    # -----------------------------------------------------------------------
    ENGINE_CMD_NEW="${ENGINE_CMD}"  # TODO: point to new version when testing
    echo "Starting SPRT test (stopping when result is statistically significant)..."
    PGN="${RESULTS_DIR}/sprt_${TS}.pgn"

    cutechess-cli \
      -engine cmd="${ENGINE_CMD_NEW}" name="${ENGINE_NAME}-New" proto=uci \
      -engine cmd="${ENGINE_CMD}" name="${ENGINE_NAME}-Base" proto=uci \
      -each tc="${TIME_CONTROL}" \
      -sprt elo0=0 elo1=10 alpha=0.05 beta=0.05 \
      -games 1000 \
      -pgnout "${PGN}" \
      -repeat \
      -recover \
      -debug

    echo "Done. PGN saved to: ${PGN}"
    ;;

  *)
    echo "Usage: $0 [self|stockfish|sprt]"
    exit 1
    ;;
esac

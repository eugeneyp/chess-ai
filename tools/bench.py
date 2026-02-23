#!/usr/bin/env python3
"""
Benchmark: measure nodes evaluated and time per move at current search depth.

Run before and after each search improvement (alpha-beta, quiescence, etc.)
to quantify the speedup. A lower node count at the same depth indicates
more effective pruning; higher NPS indicates a faster evaluation function.

Usage: python3 tools/bench.py
"""
import subprocess
import sys
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable
ENGINE = os.path.join(REPO, "interface", "uci.py")

# 10 standard positions spanning opening, middlegame, and endgame.
# These are fixed forever — same positions used for every version comparison.
POSITIONS = [
    ("Start",        "startpos"),
    ("After 1.e4",   "startpos moves e2e4"),
    ("Sicilian",     "startpos moves e2e4 c7c5"),
    ("Italian",      "startpos moves e2e4 e7e5 g1f3 b8c6 f1c4"),
    ("London",       "startpos moves d2d4 d7d5 g1f3 g8f6 c1f4"),
    ("Mid-open",     "fen r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"),
    ("Complex mid",  "fen r2q1rk1/ppp2ppp/2np1n2/2b1p1B1/2B1P1b1/2NP1N2/PPP2PPP/R2Q1RK1 w - - 0 8"),
    ("Queen ending", "fen 6k1/ppp2ppp/8/3p4/3P4/8/PPP2PPP/6K1 w - - 0 1"),
    ("Rook ending",  "fen 8/5pk1/6p1/7p/7P/6P1/5PK1/8 w - - 0 1"),
    ("Pawn race",    "fen 8/1p4k1/p7/P1K5/8/8/8/8 w - - 0 1"),
]


def run_position(label: str, pos_spec: str) -> dict:
    """Run a single position through the engine and return metrics.

    Spawns the UCI engine as a subprocess, sends the position with a
    generous movetime (60s) so the search always completes, then parses
    the final 'info depth' line for node count, NPS, and time.

    Args:
        label: Human-readable position name for display.
        pos_spec: UCI position string (e.g. "startpos" or "fen <FEN>").

    Returns:
        Dict with keys: label, move, depth, score, nodes, nps, time_ms.
    """
    env = {**os.environ, "PYTHONPATH": REPO}
    proc = subprocess.Popen(
        [PYTHON, ENGINE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    cmds = f"uci\nisready\nposition {pos_spec}\ngo movetime 60000\n"
    proc.stdin.write(cmds)
    proc.stdin.flush()

    nodes = time_ms = nps = depth = score = 0
    move = "(none)"
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("info depth"):
            parts = line.split()

            def _get(key: str) -> int:
                try:
                    return int(parts[parts.index(key) + 1])
                except (ValueError, IndexError):
                    return 0

            depth = _get("depth")
            score = _get("cp")
            nodes = _get("nodes")
            nps = _get("nps")
            time_ms = _get("time")
        elif line.startswith("bestmove"):
            move = line.split()[1]
            break

    proc.stdin.write("quit\n")
    proc.stdin.flush()
    proc.wait(timeout=5)

    return {
        "label": label,
        "move": move,
        "depth": depth,
        "score": score,
        "nodes": nodes,
        "nps": nps,
        "time_ms": time_ms,
    }


def main() -> None:
    """Run all benchmark positions and print a summary table."""
    print(f"Chess AI engine benchmark — {PYTHON}")
    print(f"Engine: {ENGINE}")
    print()
    print(
        f"{'Position':<14} {'Move':<7} {'Depth':>5} {'Score':>6} "
        f"{'Nodes':>8} {'NPS':>8} {'Time(ms)':>9}"
    )
    print("-" * 68)

    results = []
    for label, pos in POSITIONS:
        r = run_position(label, pos)
        results.append(r)
        print(
            f"{r['label']:<14} {r['move']:<7} {r['depth']:>5} {r['score']:>6} "
            f"{r['nodes']:>8,} {r['nps']:>8,} {r['time_ms']:>9,}"
        )

    valid = [r for r in results if r["nodes"] > 0]
    if valid:
        avg_nodes = sum(r["nodes"] for r in valid) // len(valid)
        avg_time = sum(r["time_ms"] for r in valid) // len(valid)
        avg_nps = sum(r["nps"] for r in valid) // len(valid)
        print("-" * 68)
        print(
            f"{'AVERAGE':<14} {'':<7} {'':<5} {'':<6} "
            f"{avg_nodes:>8,} {avg_nps:>8,} {avg_time:>9,}"
        )
    print()
    print("Run this script again after adding alpha-beta to measure node reduction.")


if __name__ == "__main__":
    main()

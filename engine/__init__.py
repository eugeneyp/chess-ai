"""
Chess AI engine package.

This package implements a classical chess engine using negamax search with
alpha-beta pruning, quiescence search, and a hand-crafted evaluation function.

Modules:
    constants   — Piece values, PST arrays, and search parameters
    evaluate    — Static position evaluation (material + piece-square tables)
    search      — Negamax search, iterative deepening, time management
    transposition — Zobrist hashing and transposition table
    move_ordering — MVV-LVA, killer moves, history heuristic
    opening_book  — Polyglot .bin book reader
"""

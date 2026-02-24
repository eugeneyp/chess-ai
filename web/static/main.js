/**
 * Chess AI frontend — game logic and API integration.
 *
 * Architecture:
 * - chess.js (game) is the authoritative state machine for move validation,
 *   game-over detection, and FEN serialisation.
 * - chessboard.js (board) is purely visual; it is synced to game.fen() after
 *   every move.
 * - The backend is called with the current FEN; it is stateless per request.
 *
 * Player is always White; engine is always Black.
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** chess.js game state — source of truth for rules and FEN */
let game = new Chess();

/** chessboard.js board instance — visual only */
let board = null;

/** Blocks drag-and-drop while the engine is searching */
let isThinking = false;

// ---------------------------------------------------------------------------
// chessboard.js callbacks
// ---------------------------------------------------------------------------

/**
 * Called when the user starts dragging a piece.
 * Returns false to cancel the drag (snap back) if:
 *   - The engine is currently thinking
 *   - The game is over
 *   - The piece belongs to the engine (Black)
 */
function onDragStart(source, piece) {
  if (isThinking) return false;
  if (game.game_over()) return false;

  // Only allow White to drag (player is always White)
  if (piece.startsWith('b')) return false;

  return true;
}

/**
 * Called when the user drops a piece on a target square.
 * Validates the move with chess.js and triggers the engine response.
 *
 * @param {string} source - Origin square (e.g. "e2")
 * @param {string} target - Destination square (e.g. "e4")
 * @returns {string|undefined} 'snapback' if the move is illegal, else undefined
 */
function onDrop(source, target) {
  // Attempt the move — always auto-promote to queen for simplicity.
  // chess.js returns null if the move is illegal.
  const move = game.move({
    from: source,
    to: target,
    promotion: 'q',
  });

  if (move === null) {
    return 'snapback';
  }

  updateStatus();

  // If the game isn't over after our move, ask the engine to respond
  if (!game.game_over()) {
    requestEngineMove();
  }
}

/**
 * Called after a snap-back animation completes — syncs the visual board
 * to the chess.js game state (no-op in normal play, ensures consistency).
 */
function onSnapEnd() {
  board.position(game.fen());
}

// ---------------------------------------------------------------------------
// Engine communication
// ---------------------------------------------------------------------------

/**
 * Fetch the engine's best move for the current position via POST /api/move.
 *
 * Updates the board, score, and depth display once the response arrives.
 * Sets isThinking to block user interaction during the search.
 */
function requestEngineMove() {
  isThinking = true;
  setStatus('Thinking...');

  const timeLimit = parseFloat(document.getElementById('time-select').value);

  fetch('/api/move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fen: game.fen(), time_limit: timeLimit }),
  })
    .then(function (response) {
      if (!response.ok) {
        return response.json().then(function (err) {
          throw new Error(err.detail || 'Server error');
        });
      }
      return response.json();
    })
    .then(function (data) {
      // Parse the UCI move string (e.g. "e7e5" or "e7e8q")
      const from = data.move.slice(0, 2);
      const to   = data.move.slice(2, 4);
      const promo = data.move.length > 4 ? data.move[4] : 'q';

      game.move({ from: from, to: to, promotion: promo });
      board.position(game.fen());

      // Update score display — score is from engine's (Black's) perspective;
      // negate so that positive = engine is winning (shown as "Engine +X.X")
      const scorePawns = (data.score / 100).toFixed(1);
      const scoreSign  = data.score >= 0 ? '+' : '';
      document.getElementById('score-text').textContent =
        scoreSign + scorePawns + ' (engine)';

      document.getElementById('depth-text').textContent = data.depth;

      isThinking = false;
      updateStatus();
    })
    .catch(function (err) {
      console.error('Engine request failed:', err);
      setStatus('Error: ' + err.message);
      isThinking = false;
    });
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

/**
 * Update the status display based on the current game state.
 * Checks for checkmate, stalemate, draw conditions, and whose turn it is.
 */
function updateStatus() {
  if (game.in_checkmate()) {
    // If it's Black's turn and checkmate, White (player) won
    setStatus(game.turn() === 'b' ? 'You win! Checkmate.' : 'Engine wins! Checkmate.');
    return;
  }

  if (game.in_stalemate()) {
    setStatus('Draw — stalemate.');
    return;
  }

  if (game.in_threefold_repetition()) {
    setStatus('Draw — threefold repetition.');
    return;
  }

  if (game.insufficient_material()) {
    setStatus('Draw — insufficient material.');
    return;
  }

  if (game.in_draw()) {
    setStatus('Draw.');
    return;
  }

  if (game.turn() === 'w') {
    const suffix = game.in_check() ? ' (in check)' : '';
    setStatus('Your turn' + suffix);
  } else {
    setStatus('Engine is thinking...');
  }
}

/**
 * Set the status text in the status panel.
 * @param {string} text - Status message to display
 */
function setStatus(text) {
  document.getElementById('status-text').textContent = text;
}

/**
 * Reset the game to the starting position and clear all UI state.
 */
function newGame() {
  game.reset();
  board.start();
  document.getElementById('score-text').textContent = '\u2014';
  document.getElementById('depth-text').textContent = '\u2014';
  isThinking = false;
  setStatus('Your turn');
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

/**
 * Initialise chessboard.js once the DOM is ready.
 * The board is configured for White at the bottom with drag-and-drop enabled.
 */
$(document).ready(function () {
  const config = {
    draggable: true,
    position: 'start',
    onDragStart: onDragStart,
    onDrop: onDrop,
    onSnapEnd: onSnapEnd,
    pieceTheme: 'https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/img/chesspieces/wikipedia/{piece}.png',
  };

  board = Chessboard('board', config);

  // Wire up the New Game button
  document.getElementById('new-game-btn').addEventListener('click', newGame);
});

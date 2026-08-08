// Pure tic-tac-toe rules. No DOM, no Svelte — run `node src/lib/tictactoe.js` to self-check.
//
// Both peers run this identically. Moves are replicated rather than broadcast
// from an authority: the DataChannel is reliable and ordered and turns strictly
// alternate, so applying the same validated move on both sides keeps the boards
// equal. canPlay() is the single validity rule, used by the sender before it
// sends AND by the receiver before it applies, so the two can never disagree.

export const X = 'X';
export const O = 'O';

// Board is a flat array of 9: 'X' | 'O' | null, indices 0..8 left-to-right, top-to-bottom.
export function emptyBoard() {
	return Array(9).fill(null);
}

export const LINES = [
	[0, 1, 2],
	[3, 4, 5],
	[6, 7, 8], // rows
	[0, 3, 6],
	[1, 4, 7],
	[2, 5, 8], // columns
	[0, 4, 8],
	[2, 4, 6] // diagonals
];

/** The winning mark and its line, or null if nobody has won yet. */
export function winnerOf(board) {
	for (const line of LINES) {
		const [a, b, c] = line;
		if (board[a] && board[a] === board[b] && board[a] === board[c]) {
			return { mark: board[a], line };
		}
	}
	return null;
}

export function isFull(board) {
	return board.every((cell) => cell !== null);
}

/** X always opens, so the mark to move follows from how many are already down. */
export function turnOf(board) {
	return board.filter((c) => c !== null).length % 2 === 0 ? X : O;
}

/**
 * Is `mark` allowed to take cell `i` right now?
 * Guards the index, the mark, whose turn it is, whether the cell is free, and
 * whether the game is already decided.
 */
export function canPlay(board, i, mark) {
	if (!Number.isInteger(i) || i < 0 || i > 8) return false;
	if (mark !== X && mark !== O) return false;
	if (board[i] !== null) return false;
	if (turnOf(board) !== mark) return false;
	if (winnerOf(board)) return false;
	return true;
}

/** Returns a NEW board with the move applied, or null if the move is illegal. */
export function applyMove(board, i, mark) {
	if (!canPlay(board, i, mark)) return null;
	const next = board.slice();
	next[i] = mark;
	return next;
}

// ponytail: assert-based self-check instead of a test framework.
function demo() {
	const assert = (cond, msg) => {
		if (!cond) throw new Error('FAIL: ' + msg);
	};
	const from = (s) => s.split('').map((c) => (c === '.' ? null : c));

	// --- every line wins, for both marks ---
	for (const line of LINES) {
		for (const mark of [X, O]) {
			const b = emptyBoard();
			for (const i of line) b[i] = mark;
			const w = winnerOf(b);
			assert(w && w.mark === mark, `line ${line} should win for ${mark}`);
			assert(String(w.line) === String(line), `line ${line} should be reported back`);
		}
	}

	// --- no false positives ---
	assert(winnerOf(emptyBoard()) === null, 'empty board has no winner');
	assert(winnerOf(from('XX.......')) === null, 'two in a row is not a win');
	assert(winnerOf(from('XOX......')) === null, 'a mixed row is not a win');

	// --- draw detection: X O X / X O O / O X X, full with no line ---
	const drawn = from('XOXXOOOXX');
	assert(isFull(drawn), 'that board is full');
	assert(winnerOf(drawn) === null, 'a full board can have no winner');
	assert(!isFull(from('XOXXOOOX.')), 'a board with a gap is not full');

	// --- turn order: X opens, then strict alternation ---
	assert(turnOf(emptyBoard()) === X, 'X moves first');
	assert(turnOf(from('X........')) === O, 'O moves second');
	assert(turnOf(from('XO.......')) === X, 'X moves third');

	// --- canPlay guards ---
	const b = from('X........');
	assert(canPlay(b, 1, O), 'O may take a free cell on its turn');
	assert(!canPlay(b, 1, X), 'X may not move twice in a row');
	assert(!canPlay(b, 0, O), 'an occupied cell is rejected');
	assert(!canPlay(b, 9, O), 'out-of-range index is rejected');
	assert(!canPlay(b, -1, O), 'negative index is rejected');
	assert(!canPlay(b, 1.5, O), 'non-integer index is rejected');
	assert(!canPlay(b, '1', O), 'string index is rejected');
	assert(!canPlay(b, undefined, O), 'missing index is rejected');
	assert(!canPlay(b, 1, 'Z'), 'unknown mark is rejected');
	assert(!canPlay(b, 1, null), 'missing mark is rejected');

	// --- no moves after the game is decided ---
	const won = from('XXXOO....');
	assert(winnerOf(won)?.mark === X, 'that board is already won by X');
	assert(!canPlay(won, 8, O), 'no moves are allowed once someone has won');

	// --- applyMove does not mutate, and rejects illegal moves ---
	const before = from('X........');
	const after = applyMove(before, 4, O);
	assert(after[4] === O, 'the move lands');
	assert(before[4] === null, 'applyMove must not mutate its input');
	assert(applyMove(before, 0, O) === null, 'illegal move returns null');

	// --- both peers applying the same move sequence get identical boards ---
	const seq = [
		[0, X],
		[4, O],
		[1, X],
		[5, O],
		[2, X]
	];
	const replay = () => seq.reduce((acc, [i, mark]) => applyMove(acc, i, mark), emptyBoard());
	assert(String(replay()) === String(replay()), 'replaying a sequence is deterministic');
	const end = replay();
	assert(winnerOf(end)?.mark === X, 'X wins the top row in that sequence');

	console.log('tictactoe.js: all checks passed');
}

if (typeof process !== 'undefined' && process.argv?.[1]?.endsWith('tictactoe.js')) demo();

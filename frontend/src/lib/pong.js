// Pure Pong/air-hockey physics in normalised "host space" coordinates (0..1 on
// both axes). The host paddle roams the left half, the guest paddle the right
// half. The guest mirrors on draw only (x -> 1-x), so both players see
// themselves on the left.
// No DOM, no Svelte — run `node src/lib/pong.js` to self-check.

export const BALL_R = 0.018;
export const PADDLE_H = 0.2;
export const PADDLE_W = 0.028;
// Where a paddle rests when its owner's face is centred (or absent), measured
// from its own goal. Leaves room to advance and to retreat.
export const HOME_X = 0.16;

const START_SPEED = 0.45; // units per second
const SPEEDUP = 1.05;
const MAX_SPEED = 1.3;
const MAX_DT = 0.05; // clamp so a throttled tab can't fast-forward the rally
// At MAX_SPEED a substep advances the ball 0.0104, well under PADDLE_W, so the
// ball can never step clean through a paddle.
const SUBSTEP = 0.008;
const MIN_VX_FRACTION = 0.25; // stops the ball settling into a vertical loop
const SPIN = 0.35; // angle added by hitting away from the paddle's centre

export function newGame() {
	return { ball: centreBall(1), score: { host: 0, guest: 0 }, speed: START_SPEED, scored: null };
}

// serveDir: +1 sends the ball towards the guest (right), -1 towards the host.
function centreBall(serveDir) {
	return { x: 0.5, y: 0.5, vx: serveDir * START_SPEED, vy: START_SPEED * 0.35 };
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** Where a side's paddle sits at kick-off, in host space. */
export function homePaddle(side) {
	return { x: side === 'host' ? HOME_X : 1 - HOME_X, y: 0.5 };
}

/**
 * Confine a paddle to its own half, in host space.
 * Also the trust boundary for paddle positions arriving from the peer — the
 * host must never feed an unclamped remote value into the simulation.
 */
export function clampPaddle(pos, side) {
	const hw = PADDLE_W / 2;
	const hh = PADDLE_H / 2;
	const x = Number.isFinite(pos?.x) ? pos.x : side === 'host' ? HOME_X : 1 - HOME_X;
	const y = Number.isFinite(pos?.y) ? pos.y : 0.5;
	return {
		x: side === 'host' ? clamp(x, hw, 0.5 - hw) : clamp(x, 0.5 + hw, 1 - hw),
		y: clamp(y, hh, 1 - hh)
	};
}

/**
 * Advance the game by dt seconds. Mutates and returns `state`.
 * hostPaddle / guestPaddle are {x, y} centres in host space.
 * Sets state.scored to 'host' | 'guest' | null for the caller to react to.
 */
export function step(state, dt, hostPaddle, guestPaddle) {
	dt = Math.min(dt, MAX_DT);
	state.scored = null;

	const hp = clampPaddle(hostPaddle, 'host');
	const gp = clampPaddle(guestPaddle, 'guest');

	// Substep so a fast ball resolves against the paddles instead of jumping past.
	let remaining = dt;
	while (remaining > 0 && !state.scored) {
		const h = Math.min(SUBSTEP, remaining);
		remaining -= h;
		integrate(state, h, hp, gp);
	}
	return state;
}

function integrate(state, dt, hp, gp) {
	const b = state.ball;
	b.x += b.vx * dt;
	b.y += b.vy * dt;

	// Top / bottom walls.
	if (b.y < BALL_R) {
		b.y = BALL_R;
		b.vy = Math.abs(b.vy);
	} else if (b.y > 1 - BALL_R) {
		b.y = 1 - BALL_R;
		b.vy = -Math.abs(b.vy);
	}

	bounceOffPaddle(state, hp, 1);
	bounceOffPaddle(state, gp, -1);

	if (b.x < -BALL_R) {
		state.score.guest += 1;
		state.scored = 'guest';
		state.speed = START_SPEED;
		state.ball = centreBall(-1);
	} else if (b.x > 1 + BALL_R) {
		state.score.host += 1;
		state.scored = 'host';
		state.speed = START_SPEED;
		state.ball = centreBall(1);
	}
}

/**
 * Circle-vs-rectangle. `outward` is the x direction that counts as "away from
 * this paddle's goal" (+1 for the host on the left), used only to break ties
 * when the ball centre lands exactly on the paddle centre.
 */
function bounceOffPaddle(state, p, outward) {
	const b = state.ball;
	const hw = PADDLE_W / 2;
	const hh = PADDLE_H / 2;

	// Closest point on the paddle rect to the ball centre.
	const cx = clamp(b.x, p.x - hw, p.x + hw);
	const cy = clamp(b.y, p.y - hh, p.y + hh);
	let nx = b.x - cx;
	let ny = b.y - cy;
	const dist = Math.hypot(nx, ny);

	if (dist > BALL_R) return;

	if (dist < 1e-9) {
		// Ball centre is inside the rect — eject along whichever axis is shallower.
		const penX = hw - Math.abs(b.x - p.x);
		const penY = hh - Math.abs(b.y - p.y);
		if (penX < penY) {
			const s = Math.sign(b.x - p.x) || outward;
			b.x = p.x + s * (hw + BALL_R);
			nx = s;
			ny = 0;
		} else {
			const s = Math.sign(b.y - p.y) || 1;
			b.y = p.y + s * (hh + BALL_R);
			nx = 0;
			ny = s;
		}
	} else {
		nx /= dist;
		ny /= dist;
		// Push the ball out to rest exactly on the paddle's surface.
		b.x = cx + nx * BALL_R;
		b.y = cy + ny * BALL_R;
	}

	// Only reflect if it is actually travelling into the paddle, otherwise a
	// grazing ball would get flipped back and forth on consecutive substeps.
	const into = b.vx * nx + b.vy * ny;
	if (into >= 0) return;

	b.vx -= 2 * into * nx;
	b.vy -= 2 * into * ny;

	// Hitting away from the paddle's centre steers the ball, so flat rallies
	// don't become a straight line.
	b.vy += clamp((b.y - p.y) / hh, -1, 1) * state.speed * SPIN;

	state.speed = Math.min(state.speed * SPEEDUP, MAX_SPEED);

	// Work on the unit direction so the speed-up stays honest at any angle, and
	// so the minimum-vx floor below can't be undone by a later renormalisation.
	const mag = Math.hypot(b.vx, b.vy) || 1;
	let ux = b.vx / mag;
	let uy = b.vy / mag;

	// Keep enough horizontal travel that the ball can't stall bouncing vertically.
	if (Math.abs(ux) < MIN_VX_FRACTION) {
		ux = (Math.sign(ux) || Math.sign(nx) || outward) * MIN_VX_FRACTION;
		uy = Math.sign(uy || 1) * Math.sqrt(1 - MIN_VX_FRACTION * MIN_VX_FRACTION);
	}

	b.vx = ux * state.speed;
	b.vy = uy * state.speed;
}

// ponytail: assert-based self-check instead of a test framework. `node src/lib/pong.js`
function demo() {
	const assert = (cond, msg) => {
		if (!cond) throw new Error('FAIL: ' + msg);
	};
	const inPaddle = (b, p) =>
		Math.abs(b.x - p.x) < PADDLE_W / 2 && Math.abs(b.y - p.y) < PADDLE_H / 2;

	const H = homePaddle('host');
	const G = homePaddle('guest');

	// --- paddles stay in their own half, whatever they are handed ---
	assert(clampPaddle({ x: 0.9, y: 0.5 }, 'host').x <= 0.5, 'host paddle must not cross centre');
	assert(clampPaddle({ x: 0.1, y: 0.5 }, 'guest').x >= 0.5, 'guest paddle must not cross centre');
	assert(clampPaddle({ x: -9, y: -9 }, 'host').x > 0, 'host paddle must stay on screen');
	assert(clampPaddle({ x: 99, y: 99 }, 'guest').x < 1, 'guest paddle must stay on screen');
	const junk = clampPaddle({ x: NaN, y: undefined }, 'guest');
	assert(Number.isFinite(junk.x) && Number.isFinite(junk.y), 'garbage input must not leak NaN');

	// --- walls ---
	let s = newGame();
	s.ball = { x: 0.5, y: BALL_R + 0.001, vx: 0.1, vy: -0.5 };
	step(s, 0.016, H, G);
	assert(s.ball.vy > 0, 'top wall should reflect the ball downward');

	s.ball = { x: 0.5, y: 1 - BALL_R - 0.001, vx: 0.1, vy: 0.5 };
	step(s, 0.016, H, G);
	assert(s.ball.vy < 0, 'bottom wall should reflect the ball upward');

	// --- a paddle in the way saves, speeds up, and does not concede ---
	s = newGame();
	s.ball = { x: H.x + 0.05, y: 0.5, vx: -0.5, vy: 0 };
	const before = s.speed;
	for (let i = 0; i < 20 && s.ball.vx < 0; i++) step(s, 0.016, H, G);
	assert(s.ball.vx > 0, 'host paddle should send the ball back to the right');
	assert(s.speed > before, 'a paddle hit should speed the rally up');
	assert(s.score.host === 0 && s.score.guest === 0, 'a save must not score');

	s = newGame();
	s.ball = { x: G.x - 0.05, y: 0.5, vx: 0.5, vy: 0 };
	for (let i = 0; i < 20 && s.ball.vx > 0; i++) step(s, 0.016, H, G);
	assert(s.ball.vx < 0, 'guest paddle should send the ball back to the left');

	// --- 2D: dodging sideways lets the ball through ---
	s = newGame();
	s.ball = { x: 0.4, y: 0.5, vx: -0.6, vy: 0 };
	const dodged = { x: 0.45, y: 0.5 }; // paddle pulled far off its goal line
	for (let i = 0; i < 200 && !s.scored; i++) step(s, 0.016, dodged, G);
	assert(s.scored === 'guest', 'a ball past a dodging paddle should score for the guest');

	// --- hitting off-centre imparts spin ---
	s = newGame();
	s.ball = { x: H.x + 0.05, y: 0.5, vx: -0.5, vy: 0 };
	for (let i = 0; i < 20 && s.ball.vx < 0; i++)
		step(s, 0.016, { x: H.x, y: 0.5 - PADDLE_H / 4 }, G);
	assert(s.ball.vy > 0, 'hitting below the paddle centre should push the ball down');

	// --- substepping: perfect tracking never concedes, even on long frames ---
	s = newGame();
	for (let i = 0; i < 400; i++) {
		step(s, 10, { x: H.x, y: s.ball.y }, { x: G.x, y: s.ball.y });
	}
	assert(s.score.host === 0 && s.score.guest === 0, 'perfect tracking must never concede');
	assert(s.speed <= MAX_SPEED + 1e-9, 'speed must stay under the cap');
	assert(Number.isFinite(s.ball.x) && Number.isFinite(s.ball.y), 'ball must stay finite');

	// --- the ball never comes to rest inside a paddle ---
	s = newGame();
	for (let i = 0; i < 3000; i++) {
		const hp = { x: 0.2 + 0.2 * Math.sin(i / 7), y: 0.5 + 0.4 * Math.sin(i / 11) };
		const gp = { x: 0.8 + 0.2 * Math.sin(i / 5), y: 0.5 + 0.4 * Math.cos(i / 9) };
		step(s, 0.02, hp, gp);
		assert(!inPaddle(s.ball, clampPaddle(hp, 'host')), `ball stuck in host paddle at i=${i}`);
		assert(!inPaddle(s.ball, clampPaddle(gp, 'guest')), `ball stuck in guest paddle at i=${i}`);
		assert(Number.isFinite(s.ball.x) && Number.isFinite(s.ball.y), `ball went NaN at i=${i}`);
		assert(s.ball.y >= -0.01 && s.ball.y <= 1.01, `ball escaped vertically at i=${i}`);
	}

	// --- a near-vertical hit still leaves usable horizontal travel ---
	// (the floor lives in the paddle bounce, the only place vx can shrink)
	s = newGame();
	s.ball = { x: H.x + PADDLE_W / 2 + BALL_R - 0.0005, y: 0.5, vx: -0.05, vy: 0.6 };
	step(s, 0.016, H, G);
	assert(s.ball.vx > 0, 'a glancing near-vertical hit should still be sent back');
	assert(
		Math.abs(s.ball.vx) > 0.2 * s.speed,
		'ball must not leave a paddle in a near-vertical loop'
	);

	console.log('pong.js: all checks passed');
}

if (typeof process !== 'undefined' && process.argv?.[1]?.endsWith('pong.js')) demo();

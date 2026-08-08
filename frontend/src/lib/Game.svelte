<script>
	import { onDestroy, createEventDispatcher } from 'svelte';
	import {
		newGame,
		step,
		clampPaddle,
		homePaddle,
		BALL_R,
		PADDLE_H,
		PADDLE_W,
		HOME_X
	} from '$lib/pong.js';
	import { loadNose, trackNose } from '$lib/nose.js';
	import TicTacToeBoard from '$lib/TicTacToeBoard.svelte';
	import {
		emptyBoard,
		applyMove,
		winnerOf,
		isFull,
		turnOf,
		canPlay,
		X,
		O
	} from '$lib/tictactoe.js';
	import { Gamepad2, VideoOff, Grid3x3 } from 'lucide-svelte';

	export let peer;
	export let localVideo;
	// Live camera state, owned by the chat page. The game needs both cameras on
	// because paddles are steered by nose tracking.
	export let isCamOn = true;
	export let isRemoteCamOn = true;

	const dispatch = createEventDispatcher();

	// A nose only travels across the middle of the frame, so amplify its movement
	// around a baseline captured during the countdown. X gets a smaller gain
	// because it only has to cover half the field, not the full height.
	// ponytail: fixed gains; make them settings sliders if people ask.
	const GAIN_X = 1.3;
	const GAIN_Y = 2.5;
	const STATE_HZ = 30; // host -> guest ball updates
	const PADDLE_HZ = 20; // each side -> the other
	const SMOOTHING = 12; // paddle lerp rate; detection is ~12fps, render is 60
	const INVITE_TIMEOUT_MS = 20000;
	const OVER_MS = 5000;
	const NOTICE_MS = 5000;

	const CAMERA_REQUIRED = 'Both cameras must be on to play.';

	// Measured from the art in static/assets/game-ball.svg: the ball disc covers
	// 78% of the sprite frame and sits slightly above its centre. Without these
	// the drawn ball would not line up with where it actually bounces.
	const BALL_SPRITE = '/assets/game-ball.svg';
	const BALL_ART_FRAC = 0.78;
	const BALL_ART_CX = 0.5;
	const BALL_ART_CY = 0.485;

	// idle | inviting | invited | countdown | playing | over
	let phase = 'idle';
	// Which game this session is. One phase + one kind means two games can never
	// run at once — it is structurally impossible rather than something policed.
	let kind = 'hockey'; // 'hockey' | 'ttt'
	let role = 'host';
	let countdownText = '';
	let score = { host: 0, guest: 0 };
	let finalScore = null;
	let outcome = null; // 'win' | 'lose' | 'draw' | 'stopped'

	// Tic-tac-toe. Host is X and opens; guest is O.
	let board = emptyBoard();
	let winLine = null;
	let noseWarning = '';
	let notice = ''; // transient toast; must not rely on the chat message overlay,
	// which the user can hide with the Messages toggle

	let wrap, canvas;
	let state = null;
	// Paddle positions are {x, y} in host space (host = left half, guest = right).
	let myPaddle = homePaddle('host');
	let remotePaddle = homePaddle('guest');
	let myTarget = homePaddle('host');
	let remoteTarget = homePaddle('guest');
	let nose = null; // {x, y} normalised, already mirrored to match the preview
	let baseline = null;
	let baselineSamples = [];

	let stopNose = null;
	let rafId = null;
	let lastT = 0;
	let lastPaddleSent = 0;
	let lastStateSent = 0;
	let timers = [];
	let resizeObserver = null;

	let ballImg = null; // decoded sprite
	let ballTile = null; // sprite pre-rasterised at draw size, refreshed on resize

	$: myScore = role === 'host' ? score.host : score.guest;
	$: theirScore = role === 'host' ? score.guest : score.host;
	$: mySide = role === 'host' ? 'host' : 'guest';

	$: myMark = role === 'host' ? X : O;
	$: theirMark = role === 'host' ? O : X;
	$: myTurn = kind === 'ttt' && phase === 'playing' && turnOf(board) === myMark;
	$: gameLabel = kind === 'ttt' ? 'X / O' : 'Nose Hockey';

	const sleep = (ms) => new Promise((r) => timers.push(setTimeout(r, ms)));

	// My half is drawn on the left whichever role I have, so my paddle is steered
	// in that "view space" and converted to host space for the wire and physics.
	// The guest's view is the mirror of host space, so the conversion is x -> 1-x.
	const viewToHost = (pos) => (role === 'host' ? pos : { x: 1 - pos.x, y: pos.y });

	/* ---------- camera gate ---------- */

	// Shown in the game overlay AND logged to chat. The overlay is the one that
	// matters: chat messages are hidden when the user turns Messages off.
	function showNotice(text) {
		notice = text;
		dispatch('system', text);
		timers.push(
			setTimeout(() => {
				if (notice === text) notice = '';
			}, NOTICE_MS)
		);
	}

	/* ---------- public API (called by the chat page) ---------- */

	export function invite(which = 'hockey') {
		if (phase !== 'idle') return;

		// X/O needs no camera, so the gate applies to hockey only.
		if (which === 'hockey') {
			// Never turns the camera on — it only reports why the game can't start.
			if (!isCamOn) {
				showNotice('Turn your camera on to play — the game steers your paddle by your nose.');
				return;
			}
			// isRemoteCamOn only goes false on a real CAM_STATE message, so a false here
			// is trustworthy. Blocking now avoids an invite that Accept would reject.
			if (!isRemoteCamOn) {
				showNotice(`The stranger's camera is off. ${CAMERA_REQUIRED}`);
				return;
			}
		}

		if (!peer?.send({ type: 'game_invite', kind: which })) return;
		kind = which;
		phase = 'inviting';
		if (kind === 'hockey') loadBallSprite(); // fetch now so it is ready by kick-off
		timers.push(
			setTimeout(() => {
				if (phase !== 'inviting') return;
				phase = 'idle';
				dispatch('system', 'The stranger did not respond to the game invite.');
			}, INVITE_TIMEOUT_MS)
		);
	}

	export function handleMessage(m) {
		switch (m.type) {
			case 'game_invite':
				if (phase === 'inviting') {
					// Both pressed Play at the same moment. The WebRTC offerer keeps its
					// invite and becomes host; the other side drops its own and accepts —
					// including adopting the offerer's choice of game.
					if (peer?.isOfferer) return;
					kind = m.kind ?? 'hockey';
					phase = 'invited';
					accept();
				} else if (phase === 'idle') {
					kind = m.kind ?? 'hockey';
					phase = 'invited';
				} else {
					// Mid-game or mid-countdown. Say so instead of letting the inviter
					// sit through the full 20s invite timeout.
					peer?.send({ type: 'game_decline', reason: 'busy' });
					return;
				}
				if (kind === 'hockey') loadBallSprite(); // ready by kick-off
				break;

			case 'game_accept':
				if (phase !== 'inviting') return;
				// Last gate before kick-off: we may have muted after inviting, and the
				// accept can beat our CAM_STATE to the other side. Hockey only.
				if (kind === 'hockey' && !camerasReady()) return cancelForCamera();
				role = 'host';
				peer?.send({ type: 'game_start', kind });
				begin();
				break;

			// 'invited' is included because a camera cancel can come from the inviter
			// after we have already accepted and are waiting for game_start.
			case 'game_decline':
				if (phase !== 'inviting' && phase !== 'invited') return;
				phase = 'idle';
				// Same reason text on both screens when a camera blocked the start.
				if (m.reason === 'camera') showNotice(CAMERA_REQUIRED);
				else if (m.reason === 'busy') showNotice('The stranger is already in a game.');
				else dispatch('system', 'The stranger declined the game.');
				break;

			case 'game_start':
				if (phase !== 'invited' && phase !== 'inviting') return;
				kind = m.kind ?? kind;
				role = 'guest';
				begin();
				break;

			case 'game_stop':
				finish(true);
				break;

			case 'game_move':
				// Re-validated against our own board with the same rule the sender
				// used, so a stray or hostile move can't desync us or play our mark.
				if (kind !== 'ttt' || phase !== 'playing') return;
				applyLocalMove(m.i, theirMark);
				break;

			case 'game_paddle':
				if (kind !== 'hockey') return;
				// Arrives in host space. Clamped here and again in step().
				remoteTarget = clampPaddle({ x: m.x, y: m.y }, role === 'host' ? 'guest' : 'host');
				break;

			case 'game_state':
				if (kind !== 'hockey') return;
				// Host is authoritative; the guest just mirrors it on draw.
				if (role === 'guest' && state && m.ball) {
					state.ball = m.ball;
					if (m.score) score = m.score;
				}
				break;
		}
	}

	export function reset() {
		phase = 'idle';
		countdownText = '';
		finalScore = null;
		outcome = null;
		board = emptyBoard();
		winLine = null;
		noseWarning = '';
		notice = '';
		state = null;
		stopNoseTracking();
		stopLoop();
		timers.forEach(clearTimeout);
		timers = [];
		clearCanvas();
		dispatch('active', false); // parent restores whatever layout was in use
	}

	/* ---------- invite handling ---------- */

	const camerasReady = () => isCamOn && isRemoteCamOn;

	// Abandon the pending invite and tell the other side why, so both screens show
	// the same reason. Reuses game_decline with a reason rather than adding a
	// message type; peer.js already forwards anything starting with game_.
	function cancelForCamera() {
		peer?.send({ type: 'game_decline', reason: 'camera' });
		showNotice(CAMERA_REQUIRED);
		phase = 'idle';
	}

	function accept() {
		// Re-checked at the moment of accepting — either side may have switched
		// their camera off since the invite went out.
		if (!camerasReady()) return cancelForCamera();
		peer?.send({ type: 'game_accept' });
	}

	function decline() {
		peer?.send({ type: 'game_decline' });
		phase = 'idle';
	}

	function stop() {
		finish(false);
	}

	/* ---------- tic-tac-toe ---------- */

	// The one place a move is applied, for our own clicks and the peer's alike.
	// Returns true if it was legal. canPlay() is shared with the sender side, so
	// both peers accept and reject exactly the same moves and stay in step.
	function applyLocalMove(i, mark) {
		if (!canPlay(board, i, mark)) return false;
		board = applyMove(board, i, mark);

		const won = winnerOf(board);
		if (won) {
			winLine = won.line;
			finishTicTacToe(won.mark === myMark ? 'win' : 'lose');
		} else if (isFull(board)) {
			finishTicTacToe('draw');
		}
		return true;
	}

	function playCell(i) {
		if (phase !== 'playing' || kind !== 'ttt') return;
		// Only send if it was legal for us — applyLocalMove is the gate.
		if (applyLocalMove(i, myMark)) peer?.send({ type: 'game_move', i });
	}

	// Both peers reach the same verdict from the same board, so neither has to
	// announce the result; game_stop is only for an early Stop.
	function finishTicTacToe(result) {
		outcome = result;
		phase = 'over';
		dispatch(
			'system',
			result === 'draw' ? 'X / O — draw.' : `X / O — you ${result === 'win' ? 'won' : 'lost'}.`
		);
		timers.push(
			setTimeout(() => {
				if (phase === 'over') reset();
			}, OVER_MS)
		);
	}

	/* ---------- game lifecycle ---------- */

	async function begin() {
		phase = 'countdown';
		outcome = null;
		finalScore = null;
		board = emptyBoard();
		winLine = null;

		if (kind === 'hockey') {
			score = { host: 0, guest: 0 };
			noseWarning = '';
			state = newGame();
			myPaddle = myTarget = homePaddle(mySide);
			remotePaddle = remoteTarget = homePaddle(role === 'host' ? 'guest' : 'host');
			nose = null;
			baseline = null;
			baselineSamples = [];

			dispatch('active', true); // parent forces the 50/50 camera layout
			startNoseTracking(); // the game still runs (paddles at home) if this fails
			loadBallSprite(); // falls back to a plain ball until it arrives
			startLoop();
		}

		for (const t of ['3', '2', '1', 'START!']) {
			countdownText = t;
			await sleep(700);
			if (phase !== 'countdown') return; // stopped or disconnected mid-countdown
		}

		if (kind === 'hockey') {
			baseline = baselineSamples.length
				? {
						x: baselineSamples.reduce((a, p) => a + p.x, 0) / baselineSamples.length,
						y: baselineSamples.reduce((a, p) => a + p.y, 0) / baselineSamples.length
					}
				: null;
			lastT = performance.now();
		}
		countdownText = '';
		phase = 'playing';
	}

	// Early stop, from either side and either game. A game that reached its own
	// natural end never gets here — hockey has no end condition, and X/O resolves
	// through finishTicTacToe().
	function finish(fromRemote) {
		if (phase !== 'playing' && phase !== 'countdown') return;
		if (!fromRemote) peer?.send({ type: 'game_stop' });

		if (kind === 'hockey') {
			finalScore =
				role === 'host'
					? { me: score.host, them: score.guest }
					: { me: score.guest, them: score.host };
			outcome =
				finalScore.me > finalScore.them ? 'win' : finalScore.me < finalScore.them ? 'lose' : 'draw';
			dispatch('system', `Game over — ${finalScore.me} : ${finalScore.them}`);
		} else {
			outcome = 'stopped';
			dispatch('system', 'X / O — game stopped.');
		}

		phase = 'over';
		countdownText = '';
		stopNoseTracking();
		timers.push(
			setTimeout(() => {
				if (phase === 'over') reset();
			}, OVER_MS)
		);
	}

	/* ---------- nose tracking ---------- */

	async function startNoseTracking() {
		try {
			await loadNose();
			if (phase === 'idle' || phase === 'over') return;
			stopNose = trackNose(localVideo, onNose);
		} catch (err) {
			console.warn('face tracking unavailable', err);
			noseWarning = 'Face tracking unavailable — paddle stays centred.';
		}
	}

	function stopNoseTracking() {
		stopNose?.();
		stopNose = null;
	}

	function onNose(pos) {
		nose = pos;
		// Collect a resting position while the countdown runs, so the paddle is
		// centred wherever the player's face actually sits.
		if (pos && phase === 'countdown') baselineSamples.push(pos);
	}

	/* ---------- loop ---------- */

	function startLoop() {
		if (rafId) return;
		lastT = performance.now();
		const tick = (t) => {
			rafId = requestAnimationFrame(tick);
			const dt = (t - lastT) / 1000;
			lastT = t;
			update(dt, t);
			draw();
		};
		rafId = requestAnimationFrame(tick);
	}

	function stopLoop() {
		if (rafId) cancelAnimationFrame(rafId);
		rafId = null;
	}

	function update(dt, t) {
		// Nose -> paddle, steered in "view space" where my own half is the left one.
		// No face (or no baseline yet) parks the paddle on its home spot.
		const view =
			nose == null || baseline == null
				? { x: HOME_X, y: 0.5 }
				: {
						x: HOME_X + (nose.x - baseline.x) * GAIN_X,
						y: 0.5 + (nose.y - baseline.y) * GAIN_Y
					};
		myTarget = clampPaddle(viewToHost(view), mySide);

		const k = Math.min(1, dt * SMOOTHING);
		myPaddle = {
			x: myPaddle.x + (myTarget.x - myPaddle.x) * k,
			y: myPaddle.y + (myTarget.y - myPaddle.y) * k
		};
		remotePaddle = {
			x: remotePaddle.x + (remoteTarget.x - remotePaddle.x) * k,
			y: remotePaddle.y + (remoteTarget.y - remotePaddle.y) * k
		};

		if (phase !== 'playing') return;

		if (t - lastPaddleSent > 1000 / PADDLE_HZ) {
			lastPaddleSent = t;
			peer?.send({ type: 'game_paddle', x: +myTarget.x.toFixed(3), y: +myTarget.y.toFixed(3) });
		}

		if (role === 'host') {
			// Host space: host paddle left, guest paddle right. step() re-clamps both,
			// so a bad value from the peer can't corrupt the simulation.
			step(state, dt, myPaddle, remotePaddle);
			if (state.scored) score = { ...state.score };

			if (t - lastStateSent > 1000 / STATE_HZ) {
				lastStateSent = t;
				const b = state.ball;
				peer?.send({
					type: 'game_state',
					ball: {
						x: +b.x.toFixed(4),
						y: +b.y.toFixed(4),
						vx: +b.vx.toFixed(4),
						vy: +b.vy.toFixed(4)
					},
					score: state.score
				});
			}
		} else if (state) {
			// Guest extrapolates between the host's 30Hz updates and snaps on receipt.
			const b = state.ball;
			b.x += b.vx * Math.min(dt, 0.05);
			b.y += b.vy * Math.min(dt, 0.05);
		}
	}

	/* ---------- rendering ---------- */

	function fitCanvas() {
		if (!canvas || !wrap) return;
		const dpr = Math.min(window.devicePixelRatio || 1, 2);
		canvas.width = Math.max(1, Math.round(wrap.clientWidth * dpr));
		canvas.height = Math.max(1, Math.round(wrap.clientHeight * dpr));
		buildBallTile(); // ball pixel size depends on the canvas size
	}

	async function loadBallSprite() {
		if (ballImg) return;
		try {
			const img = new Image();
			img.src = BALL_SPRITE;
			await img.decode();
			ballImg = img;
			buildBallTile();
		} catch (err) {
			// Not fatal — drawBall falls back to the plain circle.
			console.warn('ball sprite failed to load', err);
		}
	}

	// Rasterise the SVG once at its on-screen size. Drawing the SVG element
	// directly every frame would make the browser re-rasterise it at 60fps.
	function buildBallTile() {
		ballTile = null;
		if (!ballImg || !canvas?.width) return;
		const r = BALL_R * Math.min(canvas.width, canvas.height);
		const size = Math.max(8, Math.ceil((2 * r) / BALL_ART_FRAC));
		const tile = document.createElement('canvas');
		tile.width = tile.height = size;
		tile.getContext('2d').drawImage(ballImg, 0, 0, size, size);
		ballTile = tile;
	}

	function clearCanvas() {
		const ctx = canvas?.getContext('2d');
		if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
	}

	function draw() {
		const ctx = canvas?.getContext('2d');
		if (!ctx) return;
		const w = canvas.width;
		const h = canvas.height;
		ctx.clearRect(0, 0, w, h);
		if (kind !== 'hockey') return; // X/O draws in the DOM, not on the canvas
		if (phase !== 'playing' && phase !== 'countdown') return;

		// Everything below is in host space; the guest mirrors so that each player
		// always sees their own paddle on the left.
		const mx = (x) => (role === 'host' ? x : 1 - x) * w;

		ctx.strokeStyle = 'rgba(255,255,255,0.18)';
		ctx.lineWidth = 2 * (w / 800);
		ctx.setLineDash([10, 12]);
		ctx.beginPath();
		ctx.moveTo(w / 2, 0);
		ctx.lineTo(w / 2, h);
		ctx.stroke();
		ctx.setLineDash([]);

		const hostP = role === 'host' ? myPaddle : remotePaddle;
		const guestP = role === 'host' ? remotePaddle : myPaddle;
		drawPaddle(ctx, mx(hostP.x), hostP.y, w, h, role === 'host');
		drawPaddle(ctx, mx(guestP.x), guestP.y, w, h, role === 'guest');

		if (phase === 'playing' && state) {
			drawBall(ctx, mx(state.ball.x), state.ball.y * h, BALL_R * Math.min(w, h));
		}
	}

	function drawBall(ctx, px, py, r) {
		if (ballTile) {
			// BALL_ART_* line the sprite's painted disc up with the physics radius.
			const s = ballTile.width;
			ctx.drawImage(ballTile, px - s * BALL_ART_CX, py - s * BALL_ART_CY, s, s);
			return;
		}
		// Sprite not loaded yet, or failed — the plain ball keeps the game playable.
		ctx.fillStyle = '#ffffff';
		ctx.shadowColor = 'rgba(255,255,255,0.8)';
		ctx.shadowBlur = 12;
		ctx.beginPath();
		ctx.arc(px, py, r, 0, Math.PI * 2);
		ctx.fill();
		ctx.shadowBlur = 0;
	}

	function drawPaddle(ctx, cx, cy, w, h, isMine) {
		const pw = PADDLE_W * w;
		const ph = PADDLE_H * h;
		const x = cx - pw / 2;
		const y = cy * h - ph / 2;
		ctx.fillStyle = isMine ? '#facc15' : '#ffffff';
		// roundRect is missing on Safari < 16; square paddles beat throwing every frame.
		if (ctx.roundRect) {
			ctx.beginPath();
			ctx.roundRect(x, y, pw, ph, pw / 2);
			ctx.fill();
		} else {
			ctx.fillRect(x, y, pw, ph);
		}
	}

	function mountCanvas(node) {
		wrap = node;
		fitCanvas();
		resizeObserver = new ResizeObserver(fitCanvas);
		resizeObserver.observe(node);
		return {
			destroy() {
				resizeObserver?.disconnect();
				resizeObserver = null;
			}
		};
	}

	onDestroy(reset);
</script>

<div use:mountCanvas class="pointer-events-none absolute inset-0 z-40">
	<canvas bind:this={canvas} class="h-full w-full"></canvas>

	<!-- In play: score (hockey) / board (X-O), plus the shared Stop button -->
	{#if phase === 'playing'}
		{#if kind === 'hockey'}
			<div class="absolute top-4 left-1/2 flex -translate-x-1/2 items-center gap-4">
				<span class="text-3xl font-bold text-yellow-400 tabular-nums drop-shadow-lg">{myScore}</span
				>
				<span class="text-xl font-bold text-white/40">:</span>
				<span class="text-3xl font-bold text-white tabular-nums drop-shadow-lg">{theirScore}</span>
			</div>

			{#if noseWarning}
				<p class="absolute bottom-4 left-1/2 -translate-x-1/2 text-xs text-yellow-300/80">
					{noseWarning}
				</p>
			{/if}
		{:else}
			<div class="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-sm">
				<TicTacToeBoard {board} {myMark} {myTurn} {winLine} on:move={(e) => playCell(e.detail)} />
			</div>
		{/if}

		<button
			on:click={stop}
			class="pointer-events-auto absolute top-4 right-4 rounded-full bg-red-500 px-5 py-2 text-sm font-bold text-white shadow-lg transition hover:bg-red-400 active:scale-95"
		>
			Stop
		</button>
	{/if}

	<!-- Countdown -->
	{#if phase === 'countdown'}
		<div class="absolute inset-0 flex flex-col items-center justify-center bg-black/40">
			{#key countdownText}
				<p
					class="animate-in zoom-in text-7xl font-black text-yellow-400 drop-shadow-2xl duration-300"
				>
					{countdownText}
				</p>
			{/key}
			<p class="mt-4 text-sm text-white/70">Move your nose up and down to steer your paddle</p>
		</div>
	{/if}

	<!-- Incoming invite -->
	{#if phase === 'invited'}
		<div class="absolute inset-0 flex items-center justify-center bg-black/70 backdrop-blur-sm">
			<div
				class="pointer-events-auto w-full max-w-xs rounded-2xl border border-gray-800 bg-gray-900 p-6 text-center shadow-2xl"
			>
				{#if kind === 'ttt'}
					<Grid3x3 class="mx-auto mb-3 h-10 w-10 text-yellow-400" />
				{:else}
					<Gamepad2 class="mx-auto mb-3 h-10 w-10 text-yellow-400" />
				{/if}
				<p class="mb-1 text-lg font-bold text-white">{gameLabel} invite</p>
				<p class="mb-5 text-sm text-gray-400">
					{#if kind === 'ttt'}
						The stranger wants to play X / O. They are X and move first — no camera needed.
					{:else}
						The stranger wants to play Nose Hockey. Steer your paddle with your nose!
					{/if}
				</p>
				<div class="flex gap-3">
					<button
						on:click={decline}
						class="flex-1 rounded-xl bg-gray-800 py-2.5 font-medium text-gray-300 transition hover:bg-gray-700"
					>
						Decline
					</button>
					<button
						on:click={accept}
						class="flex-1 rounded-xl bg-yellow-400 py-2.5 font-bold text-black transition hover:bg-yellow-300"
					>
						Accept
					</button>
				</div>
			</div>
		</div>
	{/if}

	<!-- Waiting for the other side -->
	{#if phase === 'inviting'}
		<div
			class="absolute top-4 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full bg-black/70 px-4 py-2 text-sm text-white backdrop-blur-sm"
		>
			<span class="h-2 w-2 animate-pulse rounded-full bg-yellow-400"></span>
			Waiting for the stranger to accept...
		</div>
	{/if}

	<!-- Why the game could not start. Deliberately outside the chat message
	     overlay, which the user can hide with the Messages toggle. -->
	{#if notice}
		<div
			class="animate-in fade-in slide-in-from-top-2 absolute top-16 left-1/2 flex max-w-[90%] -translate-x-1/2 items-center gap-2 rounded-full bg-black/80 px-4 py-2 text-center text-sm font-medium text-yellow-300 shadow-lg backdrop-blur-sm duration-300"
			role="status"
		>
			<VideoOff class="h-4 w-4 flex-none" />
			{notice}
		</div>
	{/if}

	<!-- Result -->
	{#if phase === 'over' && outcome}
		<div class="absolute inset-0 flex items-center justify-center bg-black/70 backdrop-blur-sm">
			<div class="rounded-2xl border border-gray-800 bg-gray-900 px-10 py-7 text-center shadow-2xl">
				<p class="mb-3 text-sm tracking-widest text-gray-400 uppercase">{gameLabel}</p>

				{#if kind === 'hockey' && finalScore}
					<p class="text-5xl font-black text-white tabular-nums">
						<span class="text-yellow-400">{finalScore.me}</span>
						<span class="mx-2 text-gray-600">-</span>
						<span>{finalScore.them}</span>
					</p>
				{:else if kind === 'ttt'}
					<!-- Keep the finished board on screen so the winning line is readable. -->
					<div class="flex justify-center">
						<TicTacToeBoard {board} {myMark} myTurn={false} {winLine} />
					</div>
				{/if}

				<p class="mt-4 text-lg font-bold text-white">
					{outcome === 'win'
						? 'You win!'
						: outcome === 'lose'
							? 'You lose!'
							: outcome === 'draw'
								? 'Draw!'
								: 'Game stopped'}
				</p>
			</div>
		</div>
	{/if}
</div>

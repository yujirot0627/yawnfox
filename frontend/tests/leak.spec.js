/**
 * Does an extended session leak connections?
 *
 * Drives two real browsers through N rounds of: match -> send a chat message ->
 * play X / O -> B presses Next. B is the one who leaves, deliberately: that puts
 * A on the *remote* disconnect path, which is the one under suspicion. (Pressing
 * Next yourself takes a different, simpler branch in peer.js — which is why this
 * class of bug survives manual testing.)
 *
 * The measurement is a count, not a heap delta. Heap sizes drift for a dozen
 * reasons; "how many RTCPeerConnections did the app open and never close" is a
 * whole number, and it is exactly the thing that goes wrong. Page A should hold
 * one live RTCPeerConnection and one live WebSocket no matter how many rounds
 * have run.
 *
 * X / O rather than nose hockey on purpose: no camera dependency, no 1.5 MB
 * model download, so each round is fast and deterministic. The connection
 * lifecycle under test lives in peer.js and does not care which game ran.
 *
 *   npm run test:leak            # 20 rounds
 *   CYCLES=50 npm run test:leak  # longer soak
 */
import { test, expect } from '@playwright/test';

const CYCLES = Number(process.env.CYCLES || 20);

/**
 * Counts every RTCPeerConnection and WebSocket the app constructs, by wrapping
 * the constructors before any application code runs. Injected by the test —
 * nothing in src/ is modified, so what we measure is the shipping code.
 */
function installProbe() {
	window.__probe = { pc: [], ws: [] };

	const RealPC = window.RTCPeerConnection;
	function PC(...args) {
		const instance = new RealPC(...args);
		window.__probe.pc.push(instance);
		return instance;
	}
	PC.prototype = RealPC.prototype;
	window.RTCPeerConnection = PC;

	const RealWS = window.WebSocket;
	function WS(url, ...rest) {
		const instance = new RealWS(url, ...rest);
		// The URL is recorded so signaling sockets can be told apart from Vite's
		// HMR socket, which also goes through this constructor in dev and would
		// otherwise show up as a permanent off-by-one.
		window.__probe.ws.push({ sock: instance, url: String(url) });
		return instance;
	}
	WS.prototype = RealWS.prototype;
	// peer.js compares against the global `WebSocket.OPEN`, so the statics have
	// to come along or every readyState check silently becomes undefined.
	for (const k of ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED']) WS[k] = RealWS[k];
	window.WebSocket = WS;

	window.__signaling = () => window.__probe.ws.filter((e) => e.url.includes('/api/matchmaking'));
}

const readProbe = (page) =>
	page.evaluate(() => ({
		pcTotal: window.__probe.pc.length,
		pcLive: window.__probe.pc.filter((p) => p.connectionState !== 'closed').length,
		wsTotal: window.__signaling().length,
		wsLive: window.__signaling().filter((e) => e.sock.readyState !== WebSocket.CLOSED).length
	}));

/** Wait until the newest signaling socket is open, so Start won't no-op. */
const socketReady = (page) =>
	page.waitForFunction(() => {
		const sockets = window.__signaling();
		return sockets.length > 0 && sockets[sockets.length - 1].sock.readyState === 1;
	});

const startBtn = (page) => page.getByRole('button', { name: 'Start', exact: true });
const nextBtn = (page) => page.getByRole('button', { name: 'Next', exact: true });

async function openChat(context) {
	const page = await context.newPage();
	await page.addInitScript(installProbe);
	if (process.env.VERBOSE) page.on('console', (m) => console.log(`  [page] ${m.text()}`));
	await page.goto('/chat');
	// onMount acquires the camera and builds the first peer.
	await socketReady(page);
	return page;
}

const clickIfVisible = async (locator) => {
	if (await locator.isVisible().catch(() => false)) await locator.click().catch(() => {});
};

async function matchThem(a, b) {
	// startPairing() silently returns if peer.sdpExchange is not yet OPEN, and a
	// Vite dep re-bundle can reload the page out from under us mid-run — so a
	// single click is not guaranteed to land. Retry until both sides are matched.
	await expect(async () => {
		await socketReady(a);
		await socketReady(b);
		await clickIfVisible(startBtn(a));
		await clickIfVisible(startBtn(b));
		await nextBtn(a).waitFor({ timeout: 5_000 });
		await nextBtn(b).waitFor({ timeout: 5_000 });
	}).toPass({ timeout: 60_000, intervals: [500] });
}

async function sendChat(from, to, text) {
	const input = from.locator('input[placeholder="Type a message..."]');
	await input.waitFor({ timeout: 20_000 });
	await input.fill(text);
	await input.press('Enter');
	await expect(to.getByText(text, { exact: false }).first()).toBeVisible({ timeout: 20_000 });
}

async function playTicTacToe(host, guest) {
	// The inviter becomes host and plays X, so `host` moves first.
	await host.locator('[title*="Play X / O"]').click();
	await guest.getByRole('button', { name: 'Accept' }).click();
	// begin() runs a 4-step countdown at 700ms before phase becomes 'playing'.
	const cell = host.getByRole('button', { name: /^Cell 1, empty$/ });
	await cell.waitFor({ timeout: 20_000 });
	await cell.click();
	await expect(guest.getByRole('button', { name: /^Cell 1, X$/ })).toBeVisible({
		timeout: 20_000
	});
}

test('connection count stays flat across repeated Next cycles', async ({ browser }) => {
	const ctxA = await browser.newContext({ permissions: ['camera', 'microphone'] });
	const ctxB = await browser.newContext({ permissions: ['camera', 'microphone'] });

	// Warm Vite's dep pre-bundle on a throwaway page. Otherwise the first real
	// page load can be interrupted by an optimisation reload, which lands as a
	// mysterious "nothing matched" instead of an obvious error.
	const warmup = await ctxA.newPage();
	await warmup.goto('/chat');
	await warmup.waitForLoadState('networkidle');
	await warmup.close();

	const a = await openChat(ctxA);
	const b = await openChat(ctxB);

	// Any face-detection failure would leak tensors via the un-finally'd disposal
	// in TinyYolov2Base.detect. We don't run hockey here, but catch it anyway.
	const detectionFailures = [];
	for (const page of [a, b]) {
		page.on('console', (m) => {
			if (m.text().includes('face detection failed')) detectionFailures.push(m.text());
		});
	}

	const cdp = await ctxA.newCDPSession(a);
	const heap = async () => {
		await cdp.send('HeapProfiler.collectGarbage');
		const { usedSize } = await cdp.send('Runtime.getHeapUsage');
		return Math.round(usedSize / 1024);
	};

	const rows = [];
	console.log(`\ncycle  pcTotal  pcLive  wsTotal  wsLive  heapKB   (page A)`);
	console.log(`-----  -------  ------  -------  ------  ------`);

	for (let i = 1; i <= CYCLES; i++) {
		await matchThem(a, b);
		await sendChat(a, b, `msg-${i}`);
		await playTicTacToe(a, b);

		// B leaves -> A takes the remote-disconnect path.
		await nextBtn(b).click();
		await startBtn(a).waitFor({ timeout: 30_000 });
		await startBtn(b).waitFor({ timeout: 30_000 });

		const p = await readProbe(a);
		const heapKB = await heap();
		rows.push({ cycle: i, ...p, heapKB });
		console.log(
			`${String(i).padStart(5)}  ${String(p.pcTotal).padStart(7)}  ` +
				`${String(p.pcLive).padStart(6)}  ${String(p.wsTotal).padStart(7)}  ` +
				`${String(p.wsLive).padStart(6)}  ${String(heapKB).padStart(6)}`
		);
	}

	const first = rows[0];
	const last = rows[rows.length - 1];
	const serverConns = await (await fetch('http://localhost:8000/ping')).json();

	console.log(`\n--- after ${CYCLES} cycles, page A ---`);
	console.log(`RTCPeerConnection  constructed=${last.pcTotal}  still open=${last.pcLive}`);
	console.log(`WebSocket          constructed=${last.wsTotal}  still open=${last.wsLive}`);
	console.log(
		`per-cycle PC construction rate: ${(last.pcTotal / CYCLES).toFixed(2)} (clean = 1.00)`
	);
	console.log(`heap ${first.heapKB} KB -> ${last.heapKB} KB`);
	console.log(`backend reports ${serverConns.connections} live socket(s) (clean = 2)`);
	console.log(`face-detection failures: ${detectionFailures.length}`);

	await ctxA.close();
	await ctxB.close();

	// The assertions. A page only ever needs one of each.
	expect(last.pcLive, 'live RTCPeerConnections on page A').toBe(1);
	expect(last.wsLive, 'live WebSockets on page A').toBe(1);
});

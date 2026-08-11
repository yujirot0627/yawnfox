// How long a formed match may sit without a WebRTC connection before this side
// gives up and asks to be re-queued. Override per-instance with
// options.connectTimeoutMs (used by the self-check).
const CONNECT_TIMEOUT_MS = 15000;

// Close codes where the server is saying "go away", not "try again". Retrying
// these is worse than useless — 1013 in particular means we already tripped the
// per-IP limiter, so another attempt just deepens the hole.
//   1008 origin / policy violation   1009 frame too big
//   1011 SERVER_UNAVAILABLE          1013 RATE_LIMITED
const TERMINAL_CLOSE_CODES = [1008, 1009, 1011, 1013];

// Signaling reconnection. Deliberately few attempts: the backend allows
// RATE_LIMIT_MAX=5 connections per IP per 60s (backend/store.py), and the first
// connect plus every "Next" already spend from that same budget. Initial + 4
// retries is the whole allowance; a 5th would be answered with 1013 every time.
const RECONNECT_BASE_MS = 1000;
const RECONNECT_CAP_MS = 10000;
const RECONNECT_MAX = 4;

export class PeerConnection {
	sdpExchange;
	peerConnection;
	dataChannel;
	state;
	options;
	localStream;
	closedByLocal = false;

	constructor(options, setInitialState = true) {
		this.options = options;
		this._setInitialState = setInitialState;

		this._remoteDescSet = false;
		this._pendingCandidates = [];
		this._wsBuffer = [];
		this._connectTimer = null;
		this._disconnected = false;
		this._reconnectTimer = null;
		this._retries = 0;
		// Text from a RATE_LIMITED / SERVER_UNAVAILABLE frame, held until the close
		// that follows it can surface it. See the message handler.
		this._signalingError = null;
	}

	async init() {
		if (typeof window === 'undefined') return;

		// The stream is owned by the caller (the chat page) and lives for the whole
		// session, so it is reused across every partner. A PeerConnection borrows it
		// and must never acquire or stop it — see acquireLocalMedia / releaseLocalMedia.
		this.localStream = this.options?.localStream ?? null;
		if (!this.localStream) {
			this.options?.onStateChange?.('CAMERA_FAILED');
			return;
		}

		if (this._setInitialState) {
			console.log('👋 Setting initial NOT_CONNECTED');
			this.setState('NOT_CONNECTED');
		}
		this.peerConnection = this.createPeerConnection();
		this.createSdpExchange();
	}

	/**
	 * The one and only place a signaling socket is constructed. Reconnecting is
	 * simply calling this again — every handler below attaches fresh to the new
	 * socket, so nothing has to be re-wired by hand.
	 *
	 * Synchronous on purpose. It has nothing to await, and as an async function
	 * there would be a microtask gap between closing the old socket and pointing
	 * this.sdpExchange at the new one — which is exactly where disconnect() can
	 * interleave and leave a socket owned by nobody.
	 */
	createSdpExchange() {
		// A torn-down peer never gets a new socket. Guarding here rather than at
		// the call sites means a future caller cannot forget it.
		if (this._disconnected) return;
		// Whatever we had goes before the replacement exists, so "one live
		// signaling socket per peer" holds by construction rather than by rule.
		this.sdpExchange?.close();

		const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
		const ws = new WebSocket(`${protocol}://${import.meta.env.VITE_API_DOMAIN}/api/matchmaking`);
		this.sdpExchange = ws;

		ws.addEventListener('open', () => {
			console.log('✅ signaling connected');
			this._retries = 0;
			// flush buffered messages — anything queued during an outage, including
			// ICE gathered while the socket was down, goes out here.
			this._wsBuffer.forEach((m) => ws.send(m));
			this._wsBuffer = [];
			this.options?.onSignalingState?.('open');
		});

		ws.onerror = (e) => console.log('❌ signaling error', e);

		ws.onclose = (e) => {
			console.log('🔌 signaling closed', e.code);
			// Two guards, and they cover each other's ordering hole. _disconnected
			// catches a deliberate teardown (disconnect() sets it long before it
			// closes the socket); the identity check catches a socket that a
			// reconnect has already superseded, whose close would otherwise
			// schedule yet another reconnect. Getting this wrong leaks a socket.
			if (this._disconnected || this.sdpExchange !== ws) return;
			if (TERMINAL_CLOSE_CODES.includes(e.code)) return this._signalingFailed();
			this._scheduleReconnect();
		};

		ws.addEventListener('message', (event) => {
			const message = JSON.parse(event.data);
			console.log('📨 signaling:', message.name);

			if (message.name === 'PARTNER_FOUND') this.handlePartnerFound(message.data);
			if (message.name === 'SDP_OFFER') this.handleSdpOffer(JSON.parse(message.data));
			if (message.name === 'SDP_ANSWER') this.handleSdpAnswer(JSON.parse(message.data));
			if (message.name === 'SDP_ICE_CANDIDATE') this.handleIceCandidate(JSON.parse(message.data));
			if (message.name === 'PARTNER_LEFT') {
				console.log('Stranger left.');
				if (this.state === 'CONNECTED') {
					this.disconnect('REMOTE');
				} else {
					// Matched but never connected: the partner gave up (their own
					// connect timeout, or they left mid-handshake). The user never saw
					// this stranger, so recover like a local timeout — re-queue instead
					// of showing "Stranger disconnected" for nobody.
					this._connectFailed();
				}
			}
			if (message.name === 'RATE_LIMITED' || message.name === 'SERVER_UNAVAILABLE') {
				console.warn(message.name, message.message);
				// The server sends this immediately before closing us with 1013/1011,
				// so only record it here and let onclose surface it — one source of
				// truth, and no chance of showing it twice.
				this._signalingError = message.message;
				// Not while a call is up: this can now arrive on a *reconnect* attempt
				// made mid-call, and NOT_CONNECTED would blank the chat and reset a
				// running game for a conversation that is still perfectly alive.
				if (this.state !== 'CONNECTED') this.setState('NOT_CONNECTED');
			}
		});
	}

	_scheduleReconnect() {
		if (this._disconnected) return;
		if (this._retries >= RECONNECT_MAX) return this._signalingFailed();

		// Full jitter, not a nicety: a deploy or a Redis blip drops every client at
		// the same instant, and in lockstep they all come back as one spike the
		// moment the server is up again.
		const delay =
			Math.random() * Math.min(RECONNECT_CAP_MS, RECONNECT_BASE_MS * 2 ** this._retries);
		this._retries++;
		this.options?.onSignalingState?.('reconnecting');
		clearTimeout(this._reconnectTimer);
		// ponytail: _retries resets on open, so a server that accepts then drops in a
		// loop is bounded only by the backend's own 5/60s limiter (whose 1013 is
		// terminal and stops us). Add a "healthy for 5s" gate if that ever loosens.
		this._reconnectTimer = setTimeout(() => this.createSdpExchange(), delay);
	}

	_signalingFailed() {
		this.options?.onSignalingState?.('failed', this._signalingError);
		this._signalingError = null;
	}

	/** Manual retry, from the "Try again" button. */
	reconnectSignaling() {
		this._retries = 0;
		this.createSdpExchange();
	}

	_sendSignal(obj) {
		const payload = JSON.stringify(obj);
		if (this.sdpExchange && this.sdpExchange.readyState === WebSocket.OPEN) {
			this.sdpExchange.send(payload);
		} else {
			this._wsBuffer.push(payload);
		}
	}

	createPeerConnection() {
		const conn = new RTCPeerConnection({
			iceServers: [
				{
					urls: [
						'stun:stun.l.google.com:19302',
						'stun:stun1.l.google.com:19302',
						'stun:stun2.l.google.com:19302',
						'stun:stun3.l.google.com:19302'
					]
				}
			],
			iceCandidatePoolSize: 4
		});

		// remote media
		conn.ontrack = (event) => this.options?.onRemoteMedia?.(event.streams[0]);

		// ICE candidates → send via signaling
		conn.onicecandidate = (event) => {
			if (!event.candidate) {
				console.log('ICE gathering complete');
				return;
			}
			console.log('ICE cand:', event.candidate.candidate);
			this._sendSignal({
				name: 'SDP_ICE_CANDIDATE',
				data: JSON.stringify(event.candidate)
			});
		};

		// Connection state. Both of these must go through disconnect(), not bare
		// setState: announcing DISCONNECTED_REMOTE makes the page build a
		// replacement peer, so anything that announces it without tearing this one
		// down leaves a fully live PeerConnection — socket open, tracks still
		// encoding — with nothing referencing it. Measured at one leaked peer per
		// "Next" before this. disconnect() is idempotent, which matters here
		// because both handlers fire for the same transition.
		conn.oniceconnectionstatechange = () => {
			console.log('ICE state:', conn.iceConnectionState);
			if (conn.iceConnectionState === 'connected') this.setState('CONNECTED');
			if (['disconnected', 'failed', 'closed'].includes(conn.iceConnectionState)) {
				this.disconnect('REMOTE');
			}
		};

		conn.onconnectionstatechange = () => {
			console.log('PC state:', conn.connectionState);
			if (conn.connectionState === 'connected') this.setState('CONNECTED');
			if (['disconnected', 'failed', 'closed'].includes(conn.connectionState)) {
				this.disconnect('REMOTE');
			}
		};

		// incoming data channel
		conn.ondatachannel = (event) => {
			this.dataChannel = this.setupDataChannel(event.channel);
		};

		return conn;
	}

	setupDataChannel(channel) {
		// Chat input is enabled only once the channel is open (P2P ready).
		channel.onopen = () => {
			console.log('📡 Data channel open, sending CAM_STATE');
			this.options?.onChatReady?.(true);

			// Announce our starting camera state. This lives here, rather than on the
			// offerer's channel, because both peers route through setupDataChannel —
			// the offerer via createDataChannel and the answerer via ondatachannel.
			// Only the offerer used to send it, so a peer that muted its camera before
			// pairing was seen as camera-on by the other side.
			channel.send(
				JSON.stringify({
					type: 'CAM_STATE',
					enabled: this.localStream?.getVideoTracks?.()[0]?.enabled ?? true
				})
			);
		};

		channel.onmessage = (event) => {
			if (event.data === 'BYE') {
				console.log('📨 DC message:', event.data);
				console.log('Received BYE, closing connection');
				this.disconnect('REMOTE');
				return;
			}

			try {
				const parsed = JSON.parse(event.data);

				// Ball state (30Hz) and paddles (20Hz) would flood the console; log everything else.
				if (parsed.type !== 'game_state' && parsed.type !== 'game_paddle') {
					console.log('📨 DC message:', event.data);
				}

				if (parsed.type === 'CAM_STATE') {
					this.options?.onRemoteCamState?.(parsed.enabled);
				} else if (parsed.type === 'chat') {
					this.options?.onChatMessage?.(parsed.text);
				} else if (parsed.type?.startsWith('game_')) {
					this.options?.onGameMessage?.(parsed);
				}
			} catch (err) {
				console.warn('⚠️ Could not parse data channel message:', err);
			}
		};

		channel.onclose = () => {
			console.log('📴 Data channel closed');
			this.options?.onChatReady?.(false);
			if (!this.closedByLocal) {
				this.disconnect('REMOTE');
			} else {
				console.log('🟢 Local disconnect, skipping redundant remote state');
			}
			this.closedByLocal = false;
		};

		return channel;
	}

	sendBye() {
		if (this.dataChannel?.readyState === 'open') {
			this.dataChannel.send('BYE');
		} else {
			console.log('❗ No open data channel. Skipping BYE.');
		}
		// Tear down even with no data channel. This used to return early, which
		// skipped disconnect() entirely — so leaving a pair that never finished
		// connecting left the signaling socket open and the server none the wiser.
		this.closedByLocal = true;
		this.disconnect('LOCAL');
	}

	// Send any JSON payload peer-to-peer over the WebRTC data channel.
	send(obj) {
		if (this.dataChannel?.readyState === 'open') {
			this.dataChannel.send(JSON.stringify(obj));
			return true;
		}
		return false;
	}

	// Send a chat message peer-to-peer over the WebRTC data channel.
	sendChatMessage(text) {
		const sent = this.send({ type: 'chat', text });
		if (!sent) console.log('❗ Data channel not open. Cannot send chat.');
		return sent;
	}

	disconnect(originator) {
		// Teardown runs exactly once. Several things race to call this for a single
		// disconnection — the data channel's close event fires after the channel has
		// already been closed and nulled here, and the ICE and connection state
		// handlers both report the same transition. Each extra pass reached
		// setState below, and every DISCONNECTED_REMOTE makes the page construct a
		// replacement peer, so one "Next" was building two or three of them and
		// abandoning the surplus with their sockets still open.
		if (this._disconnected) return;
		this._disconnected = true;

		// Cancel any pending reconnect. Without this the timer fires after teardown
		// and opens a socket on a peer nothing references any more — precisely the
		// orphan class the leak fix removed. createSdpExchange guards on
		// _disconnected too; both are one line and this is where being wrong costs
		// a live socket per outage.
		clearTimeout(this._reconnectTimer);

		// Inform server if we are the one leaving
		if (originator === 'LOCAL' && this.sdpExchange?.readyState === WebSocket.OPEN) {
			try {
				this.sdpExchange.send(JSON.stringify({ name: 'LEAVE' }));
			} catch (err) {
				console.warn('LEAVE send failed', err);
			}
		}

		// Close data channel
		if (this.dataChannel) {
			try {
				this.dataChannel.close();
			} catch (err) {
				console.warn('data channel close failed', err);
			}
			this.dataChannel = null;
		}

		// Close peer connection
		if (this.peerConnection && this.peerConnection.signalingState !== 'closed') {
			try {
				this.peerConnection.close();
			} catch (err) {
				console.warn('peer connection close failed', err);
			}
		}
		this.peerConnection = null;

		// Deliberately NOT stopping this.localStream: it belongs to the chat session,
		// not to this peer, and the next partner reuses it. Stopping it here would
		// also be unsafe — a stale peer (ICE reports 'disconnected' on ordinary
		// network blips, and the page builds a replacement) could tear down later and
		// kill a camera that is already live on the new peer. Release happens once,
		// in the page's onDestroy, via releaseLocalMedia().
		// The reference is kept rather than nulled: handlePartnerFound / handleSdpOffer
		// read this.localStream unguarded.

		// Close WebSocket (your backend triggers PARTNER_LEFT when this closes).
		// Unconditionally: the reference is dropped either way, and close() is legal
		// in every readyState. Guarding on OPEN meant a socket still CONNECTING was
		// dereferenced without being closed, and the spec forbids collecting a
		// CONNECTING/OPEN socket that still has listeners — so it stayed forever.
		if (this.sdpExchange) {
			try {
				this.sdpExchange.close();
			} catch (err) {
				console.warn('signaling socket close failed', err);
			}
		}
		this.sdpExchange = null;

		// Reset flags/buffers
		this._remoteDescSet = false;
		this._pendingCandidates = [];
		this._wsBuffer = [];

		this.setState(`DISCONNECTED_${originator}`);

		// Last thing, after the page has been told. options holds callbacks that
		// close over the chat page's scope, so a peer that outlives its teardown
		// would pin the whole component — both video elements, the message list,
		// the Game instance. Dropping it also neuters any late event that still
		// reaches this object: every use site is optional-chained, so they become
		// no-ops instead of driving UI for a pairing that is over.
		this.options = null;
	}

	setState(state) {
		// Any transition ends the post-match connect wait: CONNECTED because the
		// handshake succeeded, DISCONNECTED_* because the pair is already being
		// torn down (nothing else transitions while the timer is armed).
		clearTimeout(this._connectTimer);
		this.state = state;
		this.options?.onStateChange?.(state);
	}

	_connectFailed() {
		if (this.options?.onConnectFailed) {
			this.options.onConnectFailed();
		} else {
			// No handler wired: at least don't stay stuck on a dead pair.
			this.disconnect('REMOTE');
		}
	}

	handlePartnerFound(instructions) {
		// Also used by the mini game to break a tie when both peers invite at once.
		this.isOfferer = instructions === 'GO_FIRST';

		// Matched, but nothing guarantees the handshake completes: the offer may
		// never arrive and ICE may never start, which would leave both sides
		// paired forever with no event to react to. Give it a deadline. The
		// sdpExchange check closes the race where disconnect() already ran but
		// this callback was in flight.
		clearTimeout(this._connectTimer);
		this._connectTimer = setTimeout(() => {
			if (this.state !== 'CONNECTED' && this.sdpExchange) {
				console.warn('No WebRTC connection after match; giving up on this pair');
				this._connectFailed();
			}
		}, this.options?.connectTimeoutMs ?? CONNECT_TIMEOUT_MS);

		if (instructions !== 'GO_FIRST') {
			return console.log('Partner found, waiting for SDP offer ...');
		}

		console.log('Partner found, creating SDP offer and data channel');

		this.tryHandle('PARTNER_FOUND', async () => {
			const rawChannel = this.peerConnection.createDataChannel('data-channel');
			this.dataChannel = this.setupDataChannel(rawChannel);
			// setupDataChannel's onopen announces CAM_STATE for both peers.

			// ensure senders are fresh, then add tracks
			const senders = this.peerConnection.getSenders();
			senders.forEach((s) => s.track && this.peerConnection.removeTrack(s));
			this.localStream
				.getTracks()
				.forEach((t) => this.peerConnection.addTrack(t, this.localStream));

			const offer = await this.peerConnection.createOffer();
			await this.peerConnection.setLocalDescription(offer);

			this._sendSignal({
				name: 'SDP_OFFER',
				data: JSON.stringify(this.peerConnection.localDescription)
			});
		});
	}

	handleSdpOffer(offer) {
		this.tryHandle('SDP_OFFER', async () => {
			await this.peerConnection.setRemoteDescription(new RTCSessionDescription(offer));
			this._remoteDescSet = true;

			// refresh tracks
			const senders = this.peerConnection.getSenders();
			senders.forEach((s) => s.track && this.peerConnection.removeTrack(s));
			this.localStream
				.getTracks()
				.forEach((t) => this.peerConnection.addTrack(t, this.localStream));

			const answer = await this.peerConnection.createAnswer();
			await this.peerConnection.setLocalDescription(answer);

			this._sendSignal({
				name: 'SDP_ANSWER',
				data: JSON.stringify(this.peerConnection.localDescription)
			});

			// flush queued ICE
			for (const c of this._pendingCandidates) {
				try {
					await this.peerConnection.addIceCandidate(c);
				} catch (e) {
					console.warn(e);
				}
			}
			this._pendingCandidates = [];
		});
	}

	handleSdpAnswer(answer) {
		this.tryHandle('SDP_ANSWER', async () => {
			await this.peerConnection.setRemoteDescription(new RTCSessionDescription(answer));
			this._remoteDescSet = true;

			for (const c of this._pendingCandidates) {
				try {
					await this.peerConnection.addIceCandidate(c);
				} catch (e) {
					console.warn(e);
				}
			}
			this._pendingCandidates = [];
		});
	}

	handleIceCandidate(iceCandidate) {
		this.tryHandle('ICE_CANDIDATE', async () => {
			const cand = new RTCIceCandidate(iceCandidate);
			if (!this._remoteDescSet) {
				this._pendingCandidates.push(cand);
			} else {
				await this.peerConnection.addIceCandidate(cand);
			}
		});
	}

	async tryHandle(command, callback) {
		try {
			// await so async handlers' rejections land in this catch instead of
			// becoming silent unhandled promise rejections.
			await callback();
		} catch (error) {
			console.error(`Failed to handle ${command}`, error);
		}
	}
}

// --- Local capture ---------------------------------------------------------
// Acquired once per chat session and reused by every PeerConnection, so pressing
// Next costs no getUserMedia round trip and the camera light never blinks. The
// caller owns the returned stream and is responsible for releasing it.

/**
 * Open the camera and mic. Throws on failure — deliberately: the caller needs
 * err.name to tell "you denied it" from "there is no camera" from "another app
 * has it", which are three different things to tell the user and only one of
 * them is worth offering a retry for. This used to swallow the error and return
 * null, which is why the page could only ever say "permission denied".
 */
export async function acquireLocalMedia() {
	// Undefined on an insecure origin, where the getUserMedia call below would
	// throw TypeError instead of something nameable.
	if (!navigator.mediaDevices?.getUserMedia) {
		throw Object.assign(new Error('mediaDevices unavailable'), { name: 'SecurityError' });
	}
	return await navigator.mediaDevices.getUserMedia({
		video: {
			width: { ideal: 640 },
			height: { ideal: 480 },
			frameRate: { ideal: 24, max: 30 }
		},
		audio: true
	});
}

/**
 * Is camera permission hard-blocked, i.e. will the browser refuse to re-prompt?
 * Only the Permissions API can answer this, and Safari/Firefox don't implement
 * the `camera` descriptor — hence null for "cannot tell", which the caller
 * distinguishes from a definite true/false.
 */
export async function isCameraBlocked() {
	try {
		const status = await navigator.permissions.query({ name: 'camera' });
		return status.state === 'denied';
	} catch {
		return null;
	}
}

/**
 * Stop capturing and turn the camera light off. The ONLY place tracks are stopped —
 * disconnect() must not, or a stale peer could kill the live stream.
 * Call this when leaving the chat page, not when changing partner.
 */
export function releaseLocalMedia(stream) {
	stream?.getTracks().forEach((t) => t.stop());
}

// helper to create/init in one call
export async function setupPeerConnection(options, setInitialState = true) {
	const pc = new PeerConnection(options, setInitialState);
	await pc.init();
	return pc;
}

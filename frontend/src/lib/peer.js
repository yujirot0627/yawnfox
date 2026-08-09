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
		this.sdpExchange = await this.createSdpExchange();
	}

	async createSdpExchange() {
		await ensureServerAwake();

		const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
		const ws = new WebSocket(`${protocol}://${import.meta.env.VITE_API_DOMAIN}/api/matchmaking`);
		//const ws = new WebSocket(`ws://localhost:8000/api/matchmaking`);

		ws.addEventListener('open', () => {
			console.log('✅ signaling connected');
			// flush buffered messages
			this._wsBuffer.forEach((m) => ws.send(m));
			this._wsBuffer = [];
		});

		ws.onerror = (e) => console.log('❌ signaling error', e);
		ws.onclose = (e) => console.log('🔌 signaling closed', e);

		ws.addEventListener('message', (event) => {
			const message = JSON.parse(event.data);
			console.log('📨 signaling:', message.name);

			if (message.name === 'PARTNER_FOUND') this.handlePartnerFound(message.data);
			if (message.name === 'SDP_OFFER') this.handleSdpOffer(JSON.parse(message.data));
			if (message.name === 'SDP_ANSWER') this.handleSdpAnswer(JSON.parse(message.data));
			if (message.name === 'SDP_ICE_CANDIDATE') this.handleIceCandidate(JSON.parse(message.data));
			if (message.name === 'PARTNER_LEFT') {
				console.log('Stranger left.');
				this.disconnect('REMOTE');
			}
			if (message.name === 'RATE_LIMITED' || message.name === 'SERVER_UNAVAILABLE') {
				console.warn(message.name, message.message);
				alert(message.message || 'Server is busy. Please try again shortly.');
				this.setState('NOT_CONNECTED');
			}
		});

		return ws;
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

		// connection state
		conn.oniceconnectionstatechange = () => {
			console.log('ICE state:', conn.iceConnectionState);
			if (conn.iceConnectionState === 'connected') this.setState('CONNECTED');
			if (['disconnected', 'failed', 'closed'].includes(conn.iceConnectionState)) {
				this.setState('DISCONNECTED_REMOTE');
			}
		};

		conn.onconnectionstatechange = () => {
			console.log('PC state:', conn.connectionState);
			if (conn.connectionState === 'connected') this.setState('CONNECTED');
			if (['disconnected', 'failed', 'closed'].includes(conn.connectionState)) {
				this.setState('DISCONNECTED_REMOTE');
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
		// Inform server if we are the one leaving
		if (originator === 'LOCAL' && this.sdpExchange?.readyState === WebSocket.OPEN) {
			try {
				this.sdpExchange.send(JSON.stringify({ name: 'LEAVE' }));
			} catch (_) {}
		}

		// Close data channel
		if (this.dataChannel) {
			try {
				this.dataChannel.close();
			} catch (_) {}
			this.dataChannel = null;
		}

		// Close peer connection
		if (this.peerConnection && this.peerConnection.signalingState !== 'closed') {
			try {
				this.peerConnection.close();
			} catch (_) {}
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

		// Close WebSocket (your backend triggers PARTNER_LEFT when this closes)
		if (this.sdpExchange?.readyState === WebSocket.OPEN) {
			try {
				this.sdpExchange.close();
			} catch (_) {}
		}
		this.sdpExchange = null;

		// Reset flags/buffers
		this._remoteDescSet = false;
		this._pendingCandidates = [];
		this._wsBuffer = [];

		this.setState(`DISCONNECTED_${originator}`);
	}

	setState(state) {
		this.state = state;
		this.options?.onStateChange?.(state);
	}

	handlePartnerFound(instructions) {
		// Also used by the mini game to break a tie when both peers invite at once.
		this.isOfferer = instructions === 'GO_FIRST';

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

	tryHandle(command, callback) {
		try {
			callback();
		} catch (error) {
			console.error(`Failed to handle ${command}`, error);
		}
	}
}

// --- Local capture ---------------------------------------------------------
// Acquired once per chat session and reused by every PeerConnection, so pressing
// Next costs no getUserMedia round trip and the camera light never blinks. The
// caller owns the returned stream and is responsible for releasing it.

/** Open the camera and mic. Returns the stream, or null if it was refused. */
export async function acquireLocalMedia() {
	try {
		return await navigator.mediaDevices.getUserMedia({
			video: {
				width: { ideal: 640 },
				height: { ideal: 480 },
				frameRate: { ideal: 24, max: 30 }
			},
			audio: true
		});
	} catch (err) {
		console.log('enable camera failed', err);
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

// keep your existing wakeup ping
async function ensureServerAwake() {
	const lastPing = sessionStorage.getItem('lastServerWake');
	if (lastPing && Date.now() - Number(lastPing) < 5 * 60 * 1000) return;

	try {
		const res = await fetch('https://api.yawnfox.com/ping', { cache: 'no-store' });
		const data = await res.json();

		if (data?.message?.includes('waking up')) {
			sessionStorage.setItem('lastServerWake', String(Date.now()));
			alert('⏳ Waking up the server. Please wait ~30 seconds...');
			await new Promise((resolve) => setTimeout(resolve, 30000));
		}
	} catch (err) {
		console.warn('Ping failed:', err);
	}
}

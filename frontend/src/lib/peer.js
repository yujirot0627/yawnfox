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

		try {
			this.localStream = await navigator.mediaDevices.getUserMedia({
				video: {
					width: { ideal: 640 },
					height: { ideal: 480 },
					frameRate: { ideal: 24, max: 30 }
				},
				audio: true
			});
			this.options?.onLocalMedia?.(this.localStream);
		} catch (err) {
			console.log('enable camera failed', err);
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
		//const ws = new WebSocket(`${protocol}://${import.meta.env.VITE_API_DOMAIN}/api/matchmaking`);
		const ws = new WebSocket(`ws://localhost:8000/api/matchmaking`);

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
			if (message.name === 'CHAT') {
				this.options?.onChatMessage?.(message.data);
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
		channel.onmessage = (event) => {
			console.log('📨 DC message:', event.data);

			if (event.data === 'BYE') {
				console.log('Received BYE, closing connection');
				this.disconnect('REMOTE');
				return;
			}

			try {
				const parsed = JSON.parse(event.data);
				if (parsed.type === 'CAM_STATE') {
					this.options?.onRemoteCamState?.(parsed.enabled);
				} else if (parsed.chat) {
					this.options?.onChatMessage?.(parsed.chat);
				}
			} catch (err) {
				console.warn('⚠️ Could not parse data channel message:', err);
			}
		};

		channel.onclose = () => {
			console.log('📴 Data channel closed');
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
		if (!this.dataChannel) return console.log('No data channel');
		if (this.dataChannel.readyState === 'open') {
			this.dataChannel.send('BYE');
		} else {
			console.log('❗ Data channel not open. Skipping BYE.');
		}
		this.closedByLocal = true;
		this.disconnect('LOCAL');
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
		if (instructions !== 'GO_FIRST') {
			return console.log('Partner found, waiting for SDP offer ...');
		}

		console.log('Partner found, creating SDP offer and data channel');

		this.tryHandle('PARTNER_FOUND', async () => {
			const rawChannel = this.peerConnection.createDataChannel('data-channel');
			this.dataChannel = this.setupDataChannel(rawChannel);

			rawChannel.onopen = () => {
				console.log('📡 Data channel open, sending CAM_STATE');
				rawChannel.send(
					JSON.stringify({
						type: 'CAM_STATE',
						enabled: this.localStream?.getVideoTracks?.()[0]?.enabled ?? true
					})
				);
			};

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

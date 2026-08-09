<script>
	import { onMount, onDestroy, tick } from 'svelte';
	import { setupPeerConnection, acquireLocalMedia, releaseLocalMedia } from '$lib/peer.js';
	import Game from '$lib/Game.svelte';
	import {
		Video,
		VideoOff,
		MessageCircle,
		Settings,
		X,
		TriangleAlert,
		Gamepad2,
		Grid3x3
	} from 'lucide-svelte';

	let peer;
	let currentState = 'NOT_CONNECTED';
	let statusMessage = 'Ready to match!';
	let showOverlay = true;
	let isCamOn = true;
	let isRemoteCamOn = true;
	let layoutMode = 'facetime';
	let showSettings = false;
	let showMessages = true;
	let isChatReady = false; // true once the WebRTC data channel is open

	let localVideo;
	let remoteVideo;
	let gameRef;
	// Camera + mic for the whole visit to this page. Acquired once and handed to
	// every PeerConnection, so changing partner never re-opens the device; released
	// in onDestroy. isCamOn rides on this stream's track.enabled, never on stop().
	let localStream = null;
	// While a game runs the layout is forced to 50/50 with your own camera on the
	// left, matching the side your paddle is drawn on. layoutMode is only
	// overridden, never written to, so the user's choice returns on its own.
	let gameActive = false;

	// New State
	let topics = []; // Array of strings
	let topicInput = '';
	let chatInput = '';
	let messages = []; // { id, text, sender: 'local'|'remote'|'system' }

	function setState(state) {
		currentState = state;
		console.log('state: ', state);

		// Chat is gated on the data channel being open (peer.js drives it true on
		// open); reset on any non-connected transition.
		if (state !== 'CONNECTED') {
			isChatReady = false;
			gameRef?.reset(); // never leave a game running once the peer is gone
		}

		if (state === 'CONNECTING') {
			statusMessage = 'Looking for strangers...';
			showOverlay = true;
			clearMessages();
		} else if (state === 'CONNECTED') {
			statusMessage = 'Matched!';
			// Delay hiding overlay slightly or hide immediately
			setTimeout(() => {
				showOverlay = false;
			}, 500);
			addMessage('You are now chatting with a stranger.', 'system');
			if (topics.length > 0) addMessage(`Topics: ${topics.join(', ')}`, 'system');
		} else if (state === 'CAMERA_FAILED') {
			statusMessage = 'Camera permission denied!';
			showOverlay = true;
		} else if (state === 'DISCONNECTED_LOCAL') {
			statusMessage = 'You disconnected';
			showOverlay = true;
			isRemoteCamOn = true;
			addMessage('You disconnected.', 'system');
		} else if (state === 'DISCONNECTED_REMOTE') {
			statusMessage = 'Stranger disconnected';
			showOverlay = true;
			isRemoteCamOn = true;
			addMessage('Stranger disconnected.', 'system');

			// Auto restart peer to be ready
			createPeer();
		} else {
			statusMessage = 'Ready to match!';
		}
	}

	function addMessage(text, sender) {
		const msg = { id: crypto.randomUUID(), text, sender };
		messages = [...messages, msg];

		// Capacity rule: overflow logic (keep last 20)
		if (messages.length > 20) {
			messages = messages.slice(messages.length - 20);
		}
	}

	function clearMessages() {
		messages = [];
	}

	function handleChatMessage(text) {
		addMessage(text, 'remote');
	}

	// Topic Chip Logic
	function addTopic() {
		const trimmed = topicInput.trim();
		if (!trimmed) return;

		// Normalize for deduplication
		const normalized = trimmed.toLowerCase();
		if (topics.length < 3 && !topics.some((t) => t.toLowerCase() === normalized)) {
			topics = [...topics, trimmed];
		}
		topicInput = '';
	}

	function removeTopic(index) {
		if (currentState !== 'CONNECTED' && currentState !== 'CONNECTING') {
			topics = topics.filter((_, i) => i !== index);
		}
	}

	function handleTopicKeydown(e) {
		if (e.key === 'Enter') {
			e.preventDefault();
			addTopic();
		} else if (e.key === 'Backspace' && topicInput === '' && topics.length > 0) {
			removeTopic(topics.length - 1);
		}
	}

	// Single source of truth for the peer callbacks — both setup paths use it, so a
	// new callback can't be wired into only one of them.
	function peerOptions() {
		return {
			// The session's one stream. Every peer borrows it and none of them may stop
			// it, so the camera-off state simply persists: it lives on a track object
			// that outlives the peer, which is also what CAM_STATE reads on channel open.
			localStream,
			onRemoteMedia: (stream) => (remoteVideo.srcObject = stream),
			onStateChange: setState,
			onRemoteCamState: (enabled) => {
				isRemoteCamOn = enabled;
			},
			onChatMessage: handleChatMessage,
			onChatReady: (ready) => (isChatReady = ready),
			onGameMessage: (msg) => gameRef?.handleMessage(msg)
		};
	}

	onMount(async () => {
		window.setAppState = setState;

		localStream = await acquireLocalMedia();
		if (!localStream) {
			// Refused or unavailable. Nothing to chat with, so no peer and no socket.
			setState('CAMERA_FAILED');
			return;
		}
		localVideo.srcObject = localStream; // set once; it never changes again

		peer = await setupPeerConnection(peerOptions());

		isRemoteCamOn = true;
	});

	// Cleanup lives here rather than in a function returned from onMount: that
	// callback is async, so it returns a Promise, and Svelte only invokes a returned
	// cleanup when it is a function. The old return never ran.
	onDestroy(() => {
		peer?.sendBye();
		peer = null;
		// Leaving the page is the one moment the camera should actually go out.
		releaseLocalMedia(localStream);
		localStream = null;
	});

	async function createPeer() {
		peer = await setupPeerConnection(peerOptions(), false);

		// init() bails out without a socket if it was handed no stream. Don't wait on
		// a socket that was never created.
		if (!peer.sdpExchange) return;

		await waitForWebSocketOpen(peer.sdpExchange);

		// The next stranger is unknown, so assume their camera is on until CAM_STATE
		// says otherwise. isCamOn is deliberately NOT reset: the same stream carries
		// over, so a camera the user turned off stays off, and turning one back on is
		// a decision only they get to make.
		isRemoteCamOn = true;
	}

	function waitForWebSocketOpen(ws) {
		return new Promise((resolve) => {
			if (ws.readyState === WebSocket.OPEN) return resolve();
			ws.addEventListener('open', () => resolve(), { once: true });
		});
	}

	function handleRemoteVideoPlay() {
		console.log('🎥 Remote video is playing');
		// We handle overlay visibility via state
	}

	function startPairing() {
		if (!peer?.sdpExchange || peer.sdpExchange.readyState !== WebSocket.OPEN) {
			console.warn('Cannot start pairing – WebSocket not ready');
			return;
		}

		// Ensure current input is added as topic if valid
		if (topicInput.trim()) addTopic();

		if (peer.state !== 'CONNECTED') {
			peer.setState('CONNECTING');
			peer.sdpExchange.send(JSON.stringify({ name: 'PAIRING_START', topics: topics }));
		}
	}

	async function cancelPairing() {
		peer.sdpExchange.send(JSON.stringify({ name: 'PAIRING_ABORT' }));
		peer.disconnect('LOCAL');
		await createPeer();
		peer.setState('NOT_CONNECTED');
	}

	async function leavePairing() {
		peer.sendBye();
		await createPeer();
	}

	function sendChat() {
		if (!chatInput.trim() || !isChatReady) return;

		const text = chatInput.trim();
		// Send peer-to-peer over the WebRTC data channel.
		if (peer?.sendChatMessage(text)) {
			addMessage(text, 'local');
			chatInput = '';
		}
	}

	function toggleCam() {
		// enabled, never stop() — stopping would end the session's shared track and it
		// could not be turned back on.
		const videoTracks = localStream?.getVideoTracks?.();
		if (videoTracks && videoTracks.length) {
			videoTracks[0].enabled = !videoTracks[0].enabled;
			isCamOn = videoTracks[0].enabled;

			const camStateMsg = JSON.stringify({
				type: 'CAM_STATE',
				enabled: isCamOn
			});

			if (peer?.dataChannel?.readyState === 'open') {
				peer.dataChannel.send(camStateMsg);
			}
		}
	}
</script>

<svelte:head>
	<meta name="robots" content="noindex, nofollow" />
</svelte:head>

<div class="flex h-screen flex-col overflow-hidden bg-black text-white">
	<!-- Video Area -->
	<div class="relative w-full flex-1 overflow-hidden bg-gray-900">
		<!-- Main View (Remote or Split) -->
		<div
			class={`relative h-full w-full transition-all duration-300
			${gameActive || layoutMode === 'split' ? 'flex flex-col md:flex-row' : ''}`}
		>
			<!-- Remote / Main Video -->
			<div
				class={`relative overflow-hidden bg-black ${
					gameActive || layoutMode === 'split' ? 'h-1/2 md:h-full md:w-1/2' : 'h-full w-full'
				}`}
			>
				<!-- svelte-ignore a11y_media_has_caption -->
				<!-- svelte-ignore element_invalid_self_closing_tag -->
				<video
					bind:this={remoteVideo}
					autoplay
					playsinline
					on:play={handleRemoteVideoPlay}
					class="h-full w-full -scale-x-100 object-cover"
				/>

				<!-- Loading / Status Overlay -->
				{#if showOverlay}
					<div
						class="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm"
					>
						{#if currentState === 'NOT_CONNECTED'}
							<img
								src="/icon.png"
								alt="Waiting"
								width="64"
								height="64"
								class="mb-4 h-16 w-16 animate-pulse opacity-80"
							/>
							<p class="text-xl font-medium tracking-wide">Ready to Chat?</p>
						{:else if currentState === 'CONNECTING'}
							<div
								class="mb-4 h-12 w-12 animate-spin rounded-full border-4 border-yellow-400 border-t-transparent"
							></div>
							<p class="text-lg font-medium">{statusMessage}</p>
							{#if topics.length > 0}
								<div class="mt-3 flex flex-wrap justify-center gap-2">
									{#each topics as t}
										<span
											class="rounded border border-yellow-400/30 bg-yellow-400/20 px-2 py-0.5 text-sm text-yellow-300"
										>
											{t}
										</span>
									{/each}
								</div>
							{/if}
						{:else if currentState === 'CAMERA_FAILED'}
							<TriangleAlert class="mb-3 h-12 w-12 text-yellow-400" />
							<p class="text-lg font-semibold">{statusMessage}</p>
						{:else}
							<p class="text-lg font-semibold">{statusMessage}</p>
						{/if}
					</div>
				{/if}

				{#if currentState === 'CONNECTED' && !isRemoteCamOn}
					<div
						class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-gray-900/90"
					>
						<VideoOff class="mb-2 h-10 w-10 text-gray-400" />
						<p class="font-medium text-gray-400">Camera Off</p>
					</div>
				{/if}

				<!-- Messages Overlay (Floating) -->
				{#if showMessages && messages.length > 0}
					<div
						class="pointer-events-none absolute bottom-4 left-4 z-30 flex max-w-[80%] flex-col items-start gap-2"
					>
						{#each messages as msg (msg.id)}
							<div class="animate-in fade-in slide-in-from-bottom-2 duration-300">
								<span
									class={`max-w-full rounded-lg px-3 py-1.5 text-[15px] leading-relaxed font-medium break-words text-shadow-sm
									${
										msg.sender === 'local'
											? 'bg-black/40 text-white'
											: msg.sender === 'system'
												? 'bg-black/30 font-bold text-cyan-400'
												: 'bg-black/40 text-yellow-400'
									}`}
								>
									{#if msg.sender === 'local'}
										<span class="mr-1 opacity-75">You:</span>
									{:else if msg.sender === 'remote'}
										<span class="mr-1 opacity-75">Stranger:</span>
									{:else if msg.sender === 'system'}
										<span class="mr-1 text-xs tracking-wider text-cyan-200 uppercase opacity-75"
											>System:</span
										>
									{/if}
									{msg.text}
								</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Local Video -->
			<!-- svelte-ignore a11y_media_has_caption -->
			<div
				class={`z-30 overflow-hidden bg-gray-800 transition-all duration-300
				${
					gameActive
						? // order-first puts your own camera on the side your paddle is drawn:
							// top when the split is vertical, left when it is horizontal.
							'relative order-first h-1/2 border-b border-gray-700 md:h-full md:w-1/2 md:border-r md:border-b-0'
						: layoutMode === 'split'
							? 'relative h-1/2 border-t border-gray-700 md:h-full md:w-1/2 md:border-t-0 md:border-l'
							: 'absolute right-4 bottom-4 h-32 w-24 rounded-xl border-2 border-white/20 shadow-2xl sm:h-48 sm:w-36'
				}`}
			>
				<video
					bind:this={localVideo}
					autoplay
					playsinline
					muted
					class="h-full w-full -scale-x-100 object-cover"
				></video>

				{#if !isCamOn}
					<div class="absolute inset-0 flex items-center justify-center bg-gray-800">
						<VideoOff class="h-6 w-6 text-gray-400" />
					</div>
				{/if}
			</div>
		</div>

		<!-- Mini game overlay (canvas + invite/countdown/score UI) -->
		<Game
			bind:this={gameRef}
			{peer}
			{localVideo}
			{isCamOn}
			{isRemoteCamOn}
			on:system={(e) => addMessage(e.detail, 'system')}
			on:active={(e) => (gameActive = e.detail)}
		/>
	</div>

	<!-- Bottom Controls Area -->
	<div class="z-40 flex-none space-y-3 border-t border-gray-800 bg-gray-900 p-3 sm:p-4">
		<div class="mx-auto flex w-full max-w-2xl flex-col gap-3">
			<!-- Topic Chips & Input (Top Row) -->
			<!-- Fixed height container with horizontal scroll to prevent layout shift -->
			<div
				class="no-scrollbar flex h-10 items-center gap-2 overflow-x-auto overflow-y-hidden px-1 whitespace-nowrap"
			>
				{#each topics as t, i}
					<div
						class="flex flex-none items-center gap-1 rounded-full border border-yellow-400/30 bg-yellow-400/10 px-3 py-1 text-sm text-yellow-300"
					>
						<span>{t}</span>
						{#if currentState === 'NOT_CONNECTED'}
							<button on:click={() => removeTopic(i)} class="hover:text-white">×</button>
						{/if}
					</div>
				{/each}

				{#if currentState === 'NOT_CONNECTED' && topics.length < 3}
					<input
						type="text"
						bind:value={topicInput}
						on:keydown={handleTopicKeydown}
						placeholder={topics.length === 0 ? 'Add topics...' : 'Add...'}
						class="max-w-[200px] min-w-[120px] flex-none border-b-2 border-gray-600 bg-transparent pb-0.5 text-sm text-white placeholder-gray-500 transition-colors focus:border-yellow-400 focus:outline-none"
					/>
				{/if}
			</div>

			<!-- Chat Input (Middle Row) - Always visible but enabled only when connected -->
			<form on:submit|preventDefault={sendChat} class="flex items-center gap-2">
				<input
					type="text"
					bind:value={chatInput}
					disabled={!isChatReady}
					placeholder={isChatReady ? 'Type a message...' : 'Connect to chat...'}
					class="flex-1 rounded-full border border-gray-700 bg-gray-800 px-4 py-2.5 text-white placeholder-gray-500 transition focus:ring-2 focus:ring-yellow-400/50 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
				/>
				<!-- svelte-ignore a11y_consider_explicit_label -->
				<button
					type="submit"
					class="rounded-full bg-yellow-400 p-2.5 text-black transition-transform hover:bg-yellow-300 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
					disabled={!chatInput.trim() || !isChatReady}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="currentColor"
						class="h-5 w-5"
					>
						<path
							d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z"
						/>
					</svg>
				</button>
			</form>

			<!-- Buttons Row (Bottom Row) -->
			<!-- wraps because two game buttons + Next + toggles overflow narrow screens -->
			<div class="flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
				{#if ['NOT_CONNECTED', 'DISCONNECTED_LOCAL', 'DISCONNECTED_REMOTE'].includes(currentState)}
					<button
						class="h-10 rounded-full bg-yellow-400 px-6 text-base font-bold text-black shadow-lg shadow-yellow-400/20 transition-all hover:scale-105 hover:bg-yellow-300"
						on:click={startPairing}
					>
						Start
					</button>
				{:else if currentState === 'CONNECTING'}
					<button
						class="h-10 rounded-full bg-gray-700 px-6 font-medium text-white transition-all hover:bg-gray-600"
						on:click={cancelPairing}
					>
						Stop
					</button>
				{:else if currentState === 'CONNECTED'}
					<button
						class="h-10 rounded-full bg-red-500 px-6 font-bold text-white shadow-lg shadow-red-500/20 transition-all hover:scale-105 hover:bg-red-400"
						on:click={leavePairing}
					>
						Next
					</button>

					<button
						class="flex h-10 items-center gap-2 rounded-full bg-gray-700 px-4 font-bold text-white transition-all hover:scale-105 hover:bg-gray-600 disabled:cursor-not-allowed disabled:opacity-50"
						on:click={() => gameRef?.invite('hockey')}
						disabled={!isChatReady}
						title="Play Nose Hockey — steer a paddle with your nose (camera required)"
					>
						<Gamepad2 class="h-5 w-5" />
						Nose Hockey
					</button>

					<button
						class="flex h-10 items-center gap-2 rounded-full bg-gray-700 px-4 font-bold text-white transition-all hover:scale-105 hover:bg-gray-600 disabled:cursor-not-allowed disabled:opacity-50"
						on:click={() => gameRef?.invite('ttt')}
						disabled={!isChatReady}
						title="Play X / O — no camera needed"
					>
						<Grid3x3 class="h-5 w-5" />
						X / O
					</button>
				{/if}

				<div class="mx-2 h-8 w-px bg-gray-700"></div>

				<!-- Toggles -->
				<button
					on:click={toggleCam}
					class={`flex h-10 w-10 items-center justify-center rounded-full transition-colors ${isCamOn ? 'bg-gray-700 text-white hover:bg-gray-600' : 'bg-red-500/20 text-red-500 hover:bg-red-500/30'}`}
					title="Toggle Camera"
				>
					{#if isCamOn}
						<Video class="h-5 w-5" />
					{:else}
						<VideoOff class="h-5 w-5" />
					{/if}
				</button>

				<button
					on:click={() => (showMessages = !showMessages)}
					class={`flex h-10 w-10 items-center justify-center rounded-full transition-colors ${showMessages ? 'bg-gray-700 text-white hover:bg-gray-600' : 'bg-gray-800 text-gray-500'}`}
					title="Toggle Messages"
				>
					<MessageCircle class="h-5 w-5" />
				</button>

				<button
					on:click={() => (showSettings = true)}
					class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-800 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white"
					title="Settings"
				>
					<Settings class="h-5 w-5" />
				</button>
			</div>
		</div>
	</div>

	<!-- Settings Modal -->
	{#if showSettings}
		<div
			class="animate-in fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm duration-200"
		>
			<div class="w-full max-w-sm rounded-2xl border border-gray-800 bg-gray-900 p-6 shadow-2xl">
				<div class="mb-6 flex items-center justify-between">
					<h2 class="text-xl font-bold text-white">Video Settings</h2>
					<button
						on:click={() => (showSettings = false)}
						class="text-gray-400 hover:text-white"
						aria-label="Close settings"
					>
						<X class="h-5 w-5" />
					</button>
				</div>

				<div class="space-y-4" class:opacity-50={gameActive}>
					{#if gameActive}
						<p class="text-sm text-gray-400">
							Locked to 50:50 while the game is running. Your pick returns when it ends.
						</p>
					{/if}

					<label
						class="hover:bg-gray-750 flex cursor-pointer items-center justify-between rounded-xl border border-transparent bg-gray-800 p-3 transition hover:border-gray-700"
					>
						<span class="font-medium">FaceTime Style</span>
						<input
							type="radio"
							bind:group={layoutMode}
							value="facetime"
							disabled={gameActive}
							class="h-5 w-5 border-gray-600 bg-gray-700 text-yellow-400 focus:ring-yellow-400"
						/>
					</label>

					<label
						class="hover:bg-gray-750 flex cursor-pointer items-center justify-between rounded-xl border border-transparent bg-gray-800 p-3 transition hover:border-gray-700"
					>
						<span class="font-medium">Split View (50:50)</span>
						<input
							type="radio"
							bind:group={layoutMode}
							value="split"
							disabled={gameActive}
							class="h-5 w-5 border-gray-600 bg-gray-700 text-yellow-400 focus:ring-yellow-400"
						/>
					</label>
				</div>

				<button
					class="mt-6 w-full rounded-xl bg-yellow-400 py-3 font-bold text-black transition hover:bg-yellow-300"
					on:click={() => (showSettings = false)}
				>
					Done
				</button>
			</div>
		</div>
	{/if}
</div>

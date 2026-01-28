<script>
	import { onMount, tick } from 'svelte';
	import { setupPeerConnection } from '$lib/peer.js';

	let peer;
	let currentState = 'NOT_CONNECTED';
	let statusMessage = 'Ready to match!';
	let showOverlay = true;
	let isCamOn = true;
	let isRemoteCamOn = true;
	let layoutMode = 'facetime';
	let showSettings = false;
	let showMessages = true;

	let localVideo;
	let remoteVideo;

	// New State
	let topics = []; // Array of strings
	let topicInput = '';
	let chatInput = '';
	let messages = []; // { id, text, sender: 'local'|'remote'|'system' }

	function setState(state) {
		currentState = state;
		console.log('state: ', state);

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
			statusMessage = '⚠️ Camera permission denied!';
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
		const msg = { id: Date.now(), text, sender };
		messages = [...messages, msg];

		// Capacity rule: overflow logic (keep last 8)
		if (messages.length > 8) {
			messages = messages.slice(messages.length - 8);
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

	onMount(async () => {
		window.setAppState = setState;

		peer = await setupPeerConnection({
			onLocalMedia: (stream) => (localVideo.srcObject = stream),
			onRemoteMedia: (stream) => (remoteVideo.srcObject = stream),
			onStateChange: setState,
			onRemoteCamState: (enabled) => {
				isRemoteCamOn = enabled;
			},
			onChatMessage: handleChatMessage
		});

		isRemoteCamOn = true;

		return () => {
			peer?.sendBye();
			peer = null;
		};
	});

	async function createPeer() {
		peer = await setupPeerConnection(
			{
				onLocalMedia: (stream) => (localVideo.srcObject = stream),
				onRemoteMedia: (stream) => (remoteVideo.srcObject = stream),
				onStateChange: setState,
				onRemoteCamState: (enabled) => {
					isRemoteCamOn = enabled;
				},
				onChatMessage: handleChatMessage
			},
			false
		);

		await waitForWebSocketOpen(peer.sdpExchange);

		isRemoteCamOn = true;
		isCamOn = true;
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
		if (!chatInput.trim() || currentState !== 'CONNECTED') return;

		const text = chatInput.trim();
		// Send via WebSocket relay (as per plan/backend)
		if (peer?.sdpExchange?.readyState === WebSocket.OPEN) {
			peer.sdpExchange.send(JSON.stringify({ name: 'CHAT', data: text }));
			addMessage(text, 'local');
			chatInput = '';
		}
	}

	function toggleCam() {
		const videoTracks = localVideo?.srcObject?.getVideoTracks?.();
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
			${layoutMode === 'split' ? 'flex flex-col md:flex-row' : ''}`}
		>
			<!-- Remote / Main Video -->
			<div
				class={`relative overflow-hidden bg-black ${layoutMode === 'split' ? 'h-1/2 md:h-full md:w-1/2' : 'h-full w-full'}`}
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
							<img src="/icon.png" alt="Waiting" class="mb-4 h-16 w-16 animate-pulse opacity-80" />
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
						{:else}
							<p class="text-lg font-semibold">{statusMessage}</p>
						{/if}
					</div>
				{/if}

				{#if currentState === 'CONNECTED' && !isRemoteCamOn}
					<div
						class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-gray-900/90"
					>
						<span class="mb-2 text-4xl">📷🚫</span>
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
									class={`text-shadow-sm max-w-full break-words rounded-lg px-3 py-1.5 text-[15px] font-medium leading-relaxed
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
										<span class="mr-1 text-xs uppercase tracking-wider text-cyan-200 opacity-75"
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
					layoutMode === 'split'
						? 'relative h-1/2 border-t border-gray-700 md:h-full md:w-1/2 md:border-l md:border-t-0'
						: 'absolute bottom-4 right-4 h-32 w-24 rounded-xl border-2 border-white/20 shadow-2xl sm:h-48 sm:w-36'
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
						<span class="text-2xl">🚫</span>
					</div>
				{/if}
			</div>
		</div>
	</div>

	<!-- Bottom Controls Area -->
	<div class="z-40 flex-none space-y-3 border-t border-gray-800 bg-gray-900 p-3 sm:p-4">
		<div class="mx-auto flex w-full max-w-2xl flex-col gap-3">
			<!-- Topic Chips & Input (Top Row) -->
			<!-- Fixed height container with horizontal scroll to prevent layout shift -->
			<div
				class="no-scrollbar flex h-10 items-center gap-2 overflow-x-auto overflow-y-hidden whitespace-nowrap px-1"
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
						class="min-w-[120px] max-w-[200px] flex-none border-b-2 border-gray-600 bg-transparent pb-0.5 text-sm text-white placeholder-gray-500 transition-colors focus:border-yellow-400 focus:outline-none"
					/>
				{/if}
			</div>

			<!-- Chat Input (Middle Row) - Always visible but enabled only when connected -->
			<form on:submit|preventDefault={sendChat} class="flex items-center gap-2">
				<input
					type="text"
					bind:value={chatInput}
					disabled={currentState !== 'CONNECTED'}
					placeholder={currentState === 'CONNECTED' ? 'Type a message...' : 'Connect to chat...'}
					class="flex-1 rounded-full border border-gray-700 bg-gray-800 px-4 py-2.5 text-white placeholder-gray-500 transition focus:outline-none focus:ring-2 focus:ring-yellow-400/50 disabled:cursor-not-allowed disabled:opacity-50"
				/>
				<!-- svelte-ignore a11y_consider_explicit_label -->
				<button
					type="submit"
					class="rounded-full bg-yellow-400 p-2.5 text-black transition-transform hover:bg-yellow-300 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
					disabled={!chatInput.trim() || currentState !== 'CONNECTED'}
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
			<div class="flex items-center justify-center gap-4">
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
				{/if}

				<div class="mx-2 h-8 w-px bg-gray-700"></div>

				<!-- Toggles -->
				<button
					on:click={toggleCam}
					class={`flex h-10 w-10 items-center justify-center rounded-full transition-colors ${isCamOn ? 'bg-gray-700 text-white hover:bg-gray-600' : 'bg-red-500/20 text-red-500 hover:bg-red-500/30'}`}
					title="Toggle Camera"
				>
					{isCamOn ? '📷' : '🚫'}
				</button>

				<button
					on:click={() => (showMessages = !showMessages)}
					class={`flex h-10 w-10 items-center justify-center rounded-full transition-colors ${showMessages ? 'bg-gray-700 text-white hover:bg-gray-600' : 'bg-gray-800 text-gray-500'}`}
					title="Toggle Messages"
				>
					💬
				</button>

				<button
					on:click={() => (showSettings = true)}
					class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-800 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white"
					title="Settings"
				>
					⚙️
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
					<button on:click={() => (showSettings = false)} class="text-gray-400 hover:text-white"
						>✕</button
					>
				</div>

				<div class="space-y-4">
					<label
						class="hover:bg-gray-750 flex cursor-pointer items-center justify-between rounded-xl border border-transparent bg-gray-800 p-3 transition hover:border-gray-700"
					>
						<span class="font-medium">FaceTime Style</span>
						<input
							type="radio"
							bind:group={layoutMode}
							value="facetime"
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

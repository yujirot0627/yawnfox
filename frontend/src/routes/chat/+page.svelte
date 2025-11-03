<script>
	import { onMount } from 'svelte';
	import { setupPeerConnection } from '$lib/peer.js';

	let peer;
	let currentState = 'NOT_CONNECTED';
	let statusMessage = 'Ready to match!';
	let showOverlay = true;
	let isCamOn = true;
	let isRemoteCamOn = true;
	let layoutMode = 'facetime';
	let showSettings = false;

	let localVideo;
	let remoteVideo;

	function setState(state) {
		currentState = state;
		console.log('state: ', state);

		if (state === 'CONNECTING') {
			statusMessage = 'Looking for strangers...';
			showOverlay = true;
		} else if (state === 'CONNECTED') {
			statusMessage = 'Matched! Connecting...';
		} else if (state === 'CAMERA_FAILED') {
			statusMessage = '⚠️ Camera permission denied!';
			showOverlay = true;
		} else if (state === 'DISCONNECTED_LOCAL') {
			statusMessage = 'You are disconnected';
			showOverlay = true;
			isRemoteCamOn = true;
		} else if (state === 'DISCONNECTED_REMOTE') {
			statusMessage = 'Stranger disconnected';
			showOverlay = true;
			isRemoteCamOn = true;

			createPeer();
		} else {
			statusMessage = 'Ready to match!';
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
			}
		});

		isRemoteCamOn = true;

		return () => {
			// cleanup
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
				}
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
		showOverlay = false;
	}

	function startPairing() {
		if (!peer?.sdpExchange || peer.sdpExchange.readyState !== WebSocket.OPEN) {
			console.warn('Cannot start pairing – WebSocket not ready');
			return;
		}

		if (peer.state !== 'CONNECTED') {
			peer.setState('CONNECTING');
			peer.sdpExchange.send(JSON.stringify({ name: 'PAIRING_START' }));
		}
	}

	async function cancelPairing() {
		console.log('🚫 Abort pairing clicked!');
		peer.sdpExchange.send(JSON.stringify({ name: 'PAIRING_ABORT' }));
		peer.disconnect('LOCAL');
		await createPeer();
		peer.setState('NOT_CONNECTED');
	}

	async function leavePairing() {
		peer.sendBye();
		await createPeer();
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

			// Logging
			console.log('Sending CAM_STATE to peer:', camStateMsg);

			// Guarded send
			if (peer?.dataChannel?.readyState === 'open') {
				peer.dataChannel.send(camStateMsg);
			} else {
				console.warn('❌ Cannot send CAM_STATE – data channel not open');
			}
		}
	}
</script>

<div
	class="flex min-h-screen flex-col items-center justify-center bg-gray-900 px-4 py-6 text-white"
>
	<a href="/" class="mb-6 flex items-center space-x-3 transition hover:opacity-80">
		<img src="/icon.png" alt="Yawnfox Logo" class="h-12 w-12 rounded-xl opacity-80 shadow" />
		<h1 class="text-2xl font-semibold tracking-wide text-yellow-300">Yawnfox</h1>
	</a>

	<!-- Video Section -->
	<div
		class={`relative mb-6 h-[70vh] w-full overflow-hidden rounded-xl shadow sm:h-[80vh] 
  ${layoutMode === 'split' ? 'flex flex-col md:flex-row' : ''}`}
	>
		<div
			class={`relative ${layoutMode === 'split' ? 'h-1/2 w-full md:h-full md:w-1/2' : 'absolute inset-0 h-full w-full'}`}
		>
			<!-- svelte-ignore a11y_media_has_caption -->
			<!-- svelte-ignore element_invalid_self_closing_tag -->
			<video
				bind:this={remoteVideo}
				autoplay
				playsinline
				on:play={handleRemoteVideoPlay}
				class="z-0 h-full w-full -scale-x-100 transform rounded-2xl border-2 border-yellow-100 bg-gray-800 object-cover"
			/>

			{#if showOverlay}
				<div class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-black/60">
					{#if currentState === 'NOT_CONNECTED' || currentState.startsWith('DISCONNECTED') || currentState === 'CAMERA_FAILED'}
						<img src="/icon.png" alt="Waiting" class="mb-4 h-16 w-16 opacity-80" />
					{:else}
						<img src="/spinner.svg" alt="Loading" class="mb-4 h-16 w-16 animate-spin" />
					{/if}
					<p class="text-lg font-semibold text-white">{statusMessage}</p>
				</div>
			{/if}

			{#if currentState === 'CONNECTED' && !isRemoteCamOn}
				<div class="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/70">
					<img src="/icon.png" alt="Waiting" class="mb-4 h-16 w-16 opacity-80" />
					<p class="text-lg font-semibold text-white">Stranger camera is off 🎥🚫</p>
				</div>
			{/if}
		</div>

		{#if currentState === 'CONNECTED' && !isCamOn}
			<div
				class="absolute bottom-4 left-4 z-30 flex flex-col items-start rounded-lg bg-black/70 p-2 text-white"
			>
				<span class="text-sm">📷🚫 Your camera is off</span>
			</div>
		{/if}

		<!-- Floating Local Video -->
		<!-- svelte-ignore a11y_media_has_caption -->
		<video
			bind:this={localVideo}
			autoplay
			playsinline
			muted
			class={`${
				layoutMode === 'split'
					? 'h-1/2 w-full object-cover md:h-full md:w-1/2'
					: 'absolute bottom-4 right-4 aspect-video w-[50vw] max-w-[320px] sm:w-[30vw] md:w-[20vw]'
			} z-10 -scale-x-100 transform rounded-2xl border-2 border-white bg-black shadow-lg`}
		></video>
	</div>

	<div class="pairing mt-4 flex flex-wrap justify-center gap-3">
		{#if ['NOT_CONNECTED', 'DISCONNECTED_LOCAL', 'DISCONNECTED_REMOTE'].includes(currentState)}
			<button
				class="rounded-xl bg-yellow-400 px-6 py-2 font-semibold text-black shadow transition hover:bg-yellow-300"
				on:click={startPairing}>Start Chatting</button
			>
		{:else if currentState === 'CONNECTING'}
			<button
				class="rounded-xl bg-yellow-600 px-6 py-2 text-white shadow transition hover:bg-yellow-500"
				on:click={cancelPairing}>Cancel</button
			>
		{:else if currentState === 'CONNECTED'}
			<button
				class="rounded-xl bg-red-500 px-6 py-2 text-white shadow transition hover:bg-red-400"
				on:click={leavePairing}>Leave</button
			>
		{/if}

		<button
			on:click={toggleCam}
			class={`flex h-10 w-10 items-center justify-center rounded-full shadow transition 
          ${isCamOn ? 'bg-emerald-500 hover:bg-emerald-400' : 'bg-gray-500 hover:bg-gray-400'}`}
		>
			{isCamOn ? '📸' : '📷'}
		</button>

		<button
			on:click={() => (showSettings = !showSettings)}
			class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-700 shadow hover:bg-gray-600"
		>
			⚙️
		</button>
	</div>
</div>

{#if showSettings}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
		<div
			class="w-full max-w-md rounded-2xl border border-white/10 bg-gradient-to-br from-purple-800 to-indigo-900 p-6 text-white shadow-2xl backdrop-blur-md"
		>
			<div class="flex flex-col items-center space-y-4 text-center">
				<img src="/icon.png" alt="Yawnfox icon" class="h-14 w-14 rounded-xl opacity-80 shadow" />
				<h2 class="text-2xl font-bold text-yellow-300">Settings</h2>

				<div class="w-full space-y-3 text-left">
					<label class="flex items-center space-x-2">
						<input
							type="radio"
							bind:group={layoutMode}
							value="facetime"
							class="form-radio text-yellow-400 focus:ring-yellow-300"
						/>
						<span>FaceTime Style (floating local)</span>
					</label>
					<label class="flex items-center space-x-2">
						<input
							type="radio"
							bind:group={layoutMode}
							value="split"
							class="form-radio text-yellow-400 focus:ring-yellow-300"
						/>
						<span>50:50 Split (auto vertical/horizontal)</span>
					</label>
				</div>

				<button
					on:click={() => (showSettings = false)}
					class="mt-4 rounded-xl bg-yellow-400 px-5 py-2 text-black shadow transition hover:bg-yellow-300"
				>
					Close
				</button>
			</div>
		</div>
	</div>
{/if}

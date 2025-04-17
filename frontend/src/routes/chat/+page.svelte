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
        console.log('state: ',state);
        
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
	    }else if (state === "DISCONNECTED_REMOTE") {
            statusMessage = 'Stranger disconnected';
            showOverlay = true;
            isRemoteCamOn = true;

            createPeer();
        }else {
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
        peer = await setupPeerConnection({
            onLocalMedia: (stream) => (localVideo.srcObject = stream),
            onRemoteMedia: (stream) => (remoteVideo.srcObject = stream),
            onStateChange: setState,
            onRemoteCamState: (enabled) => {
                isRemoteCamOn = enabled;
            }
        },false);

        await waitForWebSocketOpen(peer.sdpExchange);

        isRemoteCamOn = true;
        isCamOn = true;
    }

    function waitForWebSocketOpen(ws) {
    return new Promise((resolve) => {
        if (ws.readyState === WebSocket.OPEN) return resolve();
        ws.addEventListener("open", () => resolve(), { once: true });
    });}

    function handleRemoteVideoPlay() {
	    console.log('🎥 Remote video is playing');
	    showOverlay = false;
    }

	function startPairing() {
        if (!peer?.sdpExchange || peer.sdpExchange.readyState !== WebSocket.OPEN) {
	        console.warn("⏳ Cannot start pairing – WebSocket not ready");
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
            console.log("📤 Sending CAM_STATE to peer:", camStateMsg);

            // Guarded send
            if (peer?.dataChannel?.readyState === 'open') {
                peer.dataChannel.send(camStateMsg);
            } else {
                console.warn("❌ Cannot send CAM_STATE – data channel not open");
            }
        }
    }

</script>

  
  
<div class="min-h-screen bg-gray-900 text-white px-4 py-6 flex flex-col justify-center items-center">
    <a href="/" class="mb-6 flex items-center space-x-3 hover:opacity-80 transition">
        <img src="/icon.png" alt="Yawnfox Logo" class="w-12 h-12 rounded-xl opacity-80 shadow" />
        <h1 class="text-2xl font-semibold text-yellow-300 tracking-wide">Yawnfox</h1>
    </a>
      
  
    <!-- Video Section -->
    <div class={`relative w-full h-[70vh] sm:h-[80vh] rounded-xl overflow-hidden shadow mb-6 
  ${layoutMode === 'split' ? 'flex flex-col md:flex-row' : ''}`}>

        <div class={`relative ${layoutMode === 'split' ? 'w-full md:w-1/2 h-1/2 md:h-full' : 'absolute inset-0 w-full h-full'}`}>
            <!-- svelte-ignore a11y_media_has_caption -->
            <!-- svelte-ignore element_invalid_self_closing_tag -->
            <video
              bind:this={remoteVideo}
              autoplay
              playsinline
              on:play={handleRemoteVideoPlay}
              class="w-full h-full rounded-2xl object-cover border-2 border-yellow-100 bg-gray-800 transform -scale-x-100 z-0"
            />
          
            {#if showOverlay}
              <div class="absolute inset-0 flex flex-col items-center justify-center bg-black/60 z-10">
                {#if currentState === 'NOT_CONNECTED' || currentState.startsWith('DISCONNECTED') || currentState === 'CAMERA_FAILED'}
                  <img src="/icon.png" alt="Waiting" class="w-16 h-16 mb-4 opacity-80" />
                {:else}
                  <img src="/spinner.svg" alt="Loading" class="w-16 h-16 mb-4 animate-spin" />
                {/if}
                <p class="text-white text-lg font-semibold">{statusMessage}</p>
              </div>
            {/if}
          
            {#if currentState === 'CONNECTED' && !isRemoteCamOn}
              <div class="absolute inset-0 flex flex-col items-center justify-center bg-black/70 z-20">
                <img src="/icon.png" alt="Waiting" class="w-16 h-16 mb-4 opacity-80" />
                <p class="text-white text-lg font-semibold">Stranger camera is off 🎥🚫</p>
              </div>
            {/if}
          </div>

        {#if currentState === 'CONNECTED' && !isCamOn}
            <div class="absolute bottom-4 left-4 flex flex-col items-start bg-black/70 text-white p-2 rounded-lg z-30">
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
            ? 'w-full md:w-1/2 h-1/2 md:h-full object-cover'
            : 'absolute bottom-4 right-4 w-[50vw] sm:w-[30vw] md:w-[20vw] max-w-[320px] aspect-video'
            } rounded-2xl shadow-lg border-2 border-white bg-black transform -scale-x-100 z-10`}
        ></video>
      </div>


    <div class="flex gap-3 mt-4 pairing flex-wrap justify-center">
        {#if ['NOT_CONNECTED', 'DISCONNECTED_LOCAL', 'DISCONNECTED_REMOTE'].includes(currentState)}
          <button
            class="bg-yellow-400 text-black font-semibold px-6 py-2 rounded-xl shadow hover:bg-yellow-300 transition"
            on:click={startPairing}
          >Start Chatting</button>
        {:else if currentState === 'CONNECTING'}
          <button
            class="bg-yellow-600 text-white px-6 py-2 rounded-xl shadow hover:bg-yellow-500 transition"
            on:click={cancelPairing}
          >Cancel</button>
        {:else if currentState === 'CONNECTED'}
          <button
            class="bg-red-500 text-white px-6 py-2 rounded-xl shadow hover:bg-red-400 transition"
            on:click={leavePairing}
          >Leave</button>
        {/if}
      
        <button
        on:click={toggleCam}
        class={`w-10 h-10 rounded-full flex items-center justify-center shadow transition 
          ${isCamOn ? 'bg-emerald-500 hover:bg-emerald-400' : 'bg-gray-500 hover:bg-gray-400'}`}
      >
        {isCamOn ? '📸' : '📷'}
      </button>
      
      
        <button
          on:click={() => showSettings = !showSettings}
          class="w-10 h-10 rounded-full bg-gray-700 hover:bg-gray-600 flex items-center justify-center shadow"
        >
          ⚙️
        </button>
      </div>
      
</div>

{#if showSettings}
  <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
    <div class="bg-gradient-to-br from-purple-800 to-indigo-900 text-white rounded-2xl p-6 w-full max-w-md shadow-2xl backdrop-blur-md border border-white/10">
      <div class="flex flex-col items-center text-center space-y-4">
        <img src="/icon.png" alt="Yawnfox icon" class="w-14 h-14 rounded-xl opacity-80 shadow" />
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
          on:click={() => showSettings = false}
          class="mt-4 bg-yellow-400 text-black px-5 py-2 rounded-xl shadow hover:bg-yellow-300 transition"
        >
          Close
        </button>
      </div>
    </div>
  </div>
{/if}


  
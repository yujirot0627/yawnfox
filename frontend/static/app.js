import { PeerConnection } from "./peer-connection.js";

let peerConnection;

async function setup() {
  peerConnection = new PeerConnection({
    onLocalMedia: (stream) => {
      document.getElementById("localVideo").srcObject = stream;
    },
    onRemoteMedia: (stream) => {
      document.getElementById("remoteVideo").srcObject = stream;
    },
    onStateChange: (state) => {
      document.body.dataset.state = state;
      window.setAppState?.(state);
    }
  });

  // ❗ Wait until peerConnection.init() completes
  await peerConnection.init();

  // Only now attach event listeners
  document.getElementById("startPairing").addEventListener("click", () => {
    if (peerConnection.state !== "CONNECTED") {
      peerConnection.setState("CONNECTING");
      peerConnection.sdpExchange.send(JSON.stringify({ name: "PAIRING_START" }));
    }
  });

  document.getElementById("abortPairing").addEventListener("click", () => {
    console.log("🚫 Abort pairing clicked!");
    peerConnection.sdpExchange.send(JSON.stringify({ name: "PAIRING_ABORT" }));
    peerConnection.disconnect("LOCAL");
  });

  document.getElementById("leavePairing").addEventListener("click", () => {
    peerConnection.sendBye();
  });

  document.getElementById("toggleCam").addEventListener("click", function () {
    const videoElement = document.getElementById("localVideo");
    const stream = videoElement.srcObject;
    const videoTracks = stream.getVideoTracks();
    videoTracks[0].enabled = !videoTracks[0].enabled;
    this.innerHTML = videoTracks[0].enabled ? "📸" : "📷";
  });
}

// Run the setup function
setup();

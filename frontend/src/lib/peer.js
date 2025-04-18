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
            err;
            console.log("enable camera failed")
            this.options?.onStateChange?.("CAMERA_FAILED");
            return;
        }
        if (this._setInitialState) {
            console.log("👋 Setting initial NOT_CONNECTED");
            this.setState("NOT_CONNECTED");
        }
        this.peerConnection = this.createPeerConnection();
        this.sdpExchange = this.createSdpExchange();
    }
    

    createSdpExchange() { // WebSocket with listeners for exchanging SDP offers and answers
        let protocol = window.location.protocol === "https:" ? "wss" : "ws";
        let ws = new WebSocket(`${protocol}://${window.location.host}/api/matchmaking`);
        //let ws = new WebSocket(`${protocol}://localhost:8000/api/matchmaking`);

        ws.addEventListener("message", (event) => {
            const message = JSON.parse(event.data);
            console.log("Received WebSocket message", message.name)
            if (message.name === "PARTNER_FOUND") this.handlePartnerFound(message.data);
            if (message.name === "SDP_OFFER") this.handleSdpOffer(JSON.parse(message.data));
            if (message.name === "SDP_ANSWER") this.handleSdpAnswer(JSON.parse(message.data));
            if (message.name === "SDP_ICE_CANDIDATE") this.handleIceCandidate(JSON.parse(message.data));
            if (message.name === "PARTNER_LEFT") {
                console.log("Stranger left. Show disconnected message.");
                this.setState("DISCONNECTED_REMOTE");
            }
        });
        
        return ws;
    }

    // sendInterests(interests) {
    //     if (this.ws && this.ws.readyState === WebSocket.OPEN && interests.length) {
    //         const message = {
    //             name: 'SUBMIT_INTERESTS',
    //             interests: interests
    //         };
    //         console.log('intersts'+message);
    //         this.ws.send(JSON.stringify(message));
    //     } else {
    //         console.error('WebSocket is not connected.');
    //     }
    // }

    createPeerConnection() {
        const conn = new RTCPeerConnection();
        conn.ontrack = event => this.options?.onRemoteMedia?.(event.streams[0]);
        conn.onicecandidate = event => {
          if (event.candidate) {
            this.sdpExchange.send(JSON.stringify({ name: "SDP_ICE_CANDIDATE", data: JSON.stringify(event.candidate) }));
          }
        };
        conn.oniceconnectionstatechange = () => {
            console.log("ICE connection state:", conn.iceConnectionState);
          if (conn.iceConnectionState === "connected") {
            this.setState("CONNECTED");
          }
          if (["disconnected", "failed", "closed"].includes(conn.iceConnectionState)) {
            this.setState("DISCONNECTED_REMOTE");
            }
        };
        conn.ondatachannel = event => {
            this.dataChannel = this.setupDataChannel(event.channel);
        };
        return conn;
    }

    setupDataChannel(channel) {
        channel.onmessage = event => {
            console.log("📨 Received data channel message", event.data);
    
            if (event.data === "BYE") {
                this.disconnect("REMOTE");
                this.setState("DISCONNECTED_REMOTE");
                console.log("Received BYE message, closing connection");
                return;
            }
    
            try {
                const parsed = JSON.parse(event.data);
    
                if (parsed.type === "CAM_STATE") {
                    this.options?.onRemoteCamState?.(parsed.enabled);
                } else if (parsed.chat) {
                    this.options?.onChatMessage?.(parsed.chat);
                }
            } catch (err) {
                console.warn("⚠️ Could not parse data channel message:", err);
            }
        };
        channel.onclose = () => {
            console.log("📴 Data channel closed");
            if (!this.closedByLocal) {
                this.disconnect("REMOTE");
                this.setState("DISCONNECTED_REMOTE");
            } else {
                console.log("🟢 Local disconnect, skipping redundant DISCONNECTED_REMOTE");
            }
        
            this.closedByLocal = false; 
        };
    
        return channel;
    }

    sendBye() {
        if (this.dataChannel === null) return console.log("No data channel");
        if (!this.dataChannel || this.dataChannel.readyState !== "open") {
            console.log("❗ Data channel not open. Skipping BYE.");
        } else {
            this.dataChannel.send("BYE");
        }
        this.closedByLocal = true;
        this.disconnect("LOCAL");
        this.setState("DISCONNECTED_LOCAL");
    }

    // disconnect(orignator) {
    //     if (this.peerConnection?.signalingState !== "closed") {
    //         this.peerConnection.close();
    //     }

    //     this.dataChannel = null;
    //     this.peerConnection.close();
    //     this.peerConnection = this.createPeerConnection();
    //     this.setState(`DISCONNECTED_${orignator}`);
    // }
    disconnect(originator) {
        // Close data channel
        if (this.dataChannel) {
            this.dataChannel.close();
            this.dataChannel = null;
        }
    
        // Close peer connection
        if (this.peerConnection?.signalingState !== "closed") {
            this.peerConnection.close();
        }
        this.peerConnection = null;
    
        // Close WebSocket
        if (this.sdpExchange?.readyState === WebSocket.OPEN) {
            this.sdpExchange.close();
        }
        this.sdpExchange = null;
    
        this.setState(`DISCONNECTED_${originator}`);
    }
    

    setState(state) {
        this.state = state;
        this.options.onStateChange(state);
    }
    handlePartnerFound(instructions) {
        if (instructions !== "GO_FIRST") {
            return console.log("Partner found, waiting for SDP offer ...");
        }
    
        console.log("Partner found, creating SDP offer and data channel");
    
        this.tryHandle("PARTNER_FOUND", async () => {
            const rawChannel = this.peerConnection.createDataChannel("data-channel");
            this.dataChannel = this.setupDataChannel(rawChannel);
    
            // 🔐 Wait until the channel is open before sending messages
            rawChannel.onopen = () => {
                console.log("📡 Data channel is open, sending CAM_STATE");
                rawChannel.send(
                    JSON.stringify({
                        type: "CAM_STATE",
                        enabled: this.localStream?.getVideoTracks?.()[0]?.enabled ?? true,
                    })
                );
            };
    
            // Add tracks
            const senders = this.peerConnection.getSenders();
            senders.forEach(sender => {
                if (sender.track) {
                    this.peerConnection.removeTrack(sender);
                }
            });
    
            this.localStream.getTracks().forEach((track) => {
                this.peerConnection.addTrack(track, this.localStream);
            });
    
            const offer = await this.peerConnection.createOffer();
            await this.peerConnection.setLocalDescription(offer);
    
            const offerJson = JSON.stringify(this.peerConnection.localDescription);
            this.sdpExchange.send(JSON.stringify({ name: "SDP_OFFER", data: offerJson }));
        });
    }
    

    handleSdpOffer(offer) {
        this.tryHandle("SDP_OFFER", async () => {
            console.log("Received SDP offer, creating SDP answer");
            await this.peerConnection.setRemoteDescription(new RTCSessionDescription(offer));
    
            // 🔧 Remove previous tracks before adding new ones
            const senders = this.peerConnection.getSenders();
            senders.forEach(sender => {
                if (sender.track) {
                    this.peerConnection.removeTrack(sender);
                }
            });
    
            this.localStream.getTracks().forEach(track => {
                this.peerConnection.addTrack(track, this.localStream);
            });
    
            const answer = await this.peerConnection.createAnswer();
            await this.peerConnection.setLocalDescription(answer);
            const answerJson = JSON.stringify(this.peerConnection.localDescription);
            this.sdpExchange.send(JSON.stringify({ name: "SDP_ANSWER", data: answerJson }));
        });
    }
    

    handleSdpAnswer(answer) { // only for the "offerer" (the one who sends the SDP offer)
        this.tryHandle("SDP_ANSWER", async () => {
            await this.peerConnection.setRemoteDescription(new RTCSessionDescription(answer));

            // ✅ Send CAM_STATE once connection is established
            if (this.dataChannel?.readyState === "open") {
	            this.dataChannel.send(JSON.stringify({
		        type: "CAM_STATE",
		        enabled: this.localStream?.getVideoTracks?.()[0]?.enabled ?? true,
	        }));
            } else {
	            this.dataChannel.onopen = () => {
		        this.dataChannel.send(JSON.stringify({
			        type: "CAM_STATE",
			        enabled: this.localStream?.getVideoTracks?.()[0]?.enabled ?? true,
		        }));
	            };
            }

        });
    }

    handleIceCandidate(iceCandidate) {
        this.tryHandle("ICE_CANDIDATE", async () => {
            await this.peerConnection.addIceCandidate(new RTCIceCandidate(iceCandidate));
        });
    }

    tryHandle(command, callback) {
        try {
            callback()
        } catch (error) {
            console.error(`Failed to handle ${command}`, error);
        }
    }
}

export async function setupPeerConnection(options, setInitialState = true) {
	const pc = new PeerConnection(options, setInitialState);
	await pc.init();
	return pc;
}



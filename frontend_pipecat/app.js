/**
 * HAL 9000 Pipecat WebRTC Frontend
 *
 * Connects to Daily.co room for low-latency voice conversation with HAL.
 */

class HALWebRTCClient {
    constructor() {
        // Daily.co call frame
        this.callFrame = null;
        this.isConnected = false;
        this.isMuted = false;
        this.speakerEnabled = true;

        // Transcript
        this.transcript = [];

        // DOM elements
        this.elements = {
            // Connection panel
            roomUrl: document.getElementById('roomUrl'),
            roomToken: document.getElementById('roomToken'),
            personName: document.getElementById('personName'),
            connectBtn: document.getElementById('connectBtn'),

            // Conversation panel
            connectionPanel: document.getElementById('connectionPanel'),
            conversationPanel: document.getElementById('conversationPanel'),

            // Status
            status: document.getElementById('status'),
            callStatus: document.getElementById('callStatus'),
            latency: document.getElementById('latency'),
            speakingStatus: document.getElementById('speakingStatus'),

            // Transcript
            transcript: document.getElementById('transcript'),

            // Controls
            muteBtn: document.getElementById('muteBtn'),
            speakerBtn: document.getElementById('speakerBtn'),
            disconnectBtn: document.getElementById('disconnectBtn'),

            // HAL eye
            halEye: document.getElementById('halEye'),

            // Visualizer
            visualizer: document.getElementById('visualizer'),
        };

        // Bind event listeners
        this.bindEvents();

        // Load settings from localStorage
        this.loadSettings();

        // Initialize visualizer
        this.initVisualizer();
    }

    bindEvents() {
        this.elements.connectBtn.addEventListener('click', () => this.connect());
        this.elements.disconnectBtn.addEventListener('click', () => this.disconnect());
        this.elements.muteBtn.addEventListener('click', () => this.toggleMute());
        this.elements.speakerBtn.addEventListener('click', () => this.toggleSpeaker());
    }

    loadSettings() {
        // Load from localStorage if available
        const savedRoomUrl = localStorage.getItem('hal_room_url');
        const savedPersonName = localStorage.getItem('hal_person_name');

        if (savedRoomUrl) {
            this.elements.roomUrl.value = savedRoomUrl;
        }
        if (savedPersonName) {
            this.elements.personName.value = savedPersonName;
        }
    }

    saveSettings() {
        localStorage.setItem('hal_room_url', this.elements.roomUrl.value);
        localStorage.setItem('hal_person_name', this.elements.personName.value);
    }

    async connect() {
        const roomUrl = this.elements.roomUrl.value.trim();
        const roomToken = this.elements.roomToken.value.trim();
        const personName = this.elements.personName.value.trim() || 'Dave';

        if (!roomUrl) {
            this.setStatus('Please enter a room URL', 'error');
            return;
        }

        try {
            this.setStatus('Connecting to HAL...', 'connecting');
            this.setEyeState('connecting');

            // Save settings
            this.saveSettings();

            // Create Daily call frame
            this.callFrame = window.DailyIframe.createFrame(
                document.getElementById('callFrame'),
                {
                    showLeaveButton: false,
                    showFullscreenButton: false,
                    iframeStyle: {
                        position: 'absolute',
                        width: '0px',
                        height: '0px',
                        border: '0',
                        visibility: 'hidden',
                    }
                }
            );

            // Set up event listeners
            this.setupCallFrameEvents();

            // Join room
            const joinConfig = {
                url: roomUrl,
                userName: personName,
            };

            if (roomToken) {
                joinConfig.token = roomToken;
            }

            await this.callFrame.join(joinConfig);

            console.log('Joined Daily.co room');

        } catch (error) {
            console.error('Connection failed:', error);
            this.setStatus(`Connection failed: ${error.message}`, 'error');
            this.setEyeState('error');
        }
    }

    setupCallFrameEvents() {
        // Joined meeting
        this.callFrame.on('joined-meeting', (event) => {
            console.log('Joined meeting:', event);
            this.isConnected = true;
            this.setStatus('Connected to HAL', 'connected');
            this.setEyeState('idle');
            this.showConversationPanel();
            this.updateCallStatus('Connected');
        });

        // Left meeting
        this.callFrame.on('left-meeting', (event) => {
            console.log('Left meeting:', event);
            this.isConnected = false;
            this.setStatus('Disconnected from HAL', 'disconnected');
            this.setEyeState('idle');
            this.hideConversationPanel();
        });

        // Error
        this.callFrame.on('error', (event) => {
            console.error('Call error:', event);
            this.setStatus(`Error: ${event.errorMsg}`, 'error');
            this.setEyeState('error');
        });

        // Participant joined
        this.callFrame.on('participant-joined', (event) => {
            console.log('Participant joined:', event);
            if (event.participant.user_name === 'HAL 9000') {
                this.addTranscript('system', 'HAL 9000 has joined the conversation');
            }
        });

        // Track started (audio)
        this.callFrame.on('track-started', (event) => {
            console.log('Track started:', event);
            if (event.track.kind === 'audio') {
                this.setEyeState('listening');
            }
        });

        // Active speaker change
        this.callFrame.on('active-speaker-change', (event) => {
            console.log('Active speaker:', event);
            const isSpeaking = event.activeSpeaker &&
                              event.activeSpeaker.peerId !== 'local';
            this.updateSpeakingStatus(isSpeaking);
            this.setEyeState(isSpeaking ? 'speaking' : 'listening');
        });

        // Network quality stats
        this.callFrame.on('network-quality-change', (event) => {
            const quality = event.threshold;
            console.log('Network quality:', quality);
            // Update latency display (simplified)
            this.updateLatency(quality === 'good' ? 50 : quality === 'low' ? 150 : 300);
        });
    }

    async disconnect() {
        if (this.callFrame) {
            await this.callFrame.leave();
            this.callFrame.destroy();
            this.callFrame = null;
        }
        this.isConnected = false;
        this.setStatus('System Standby', 'idle');
        this.setEyeState('idle');
        this.hideConversationPanel();
    }

    toggleMute() {
        if (!this.callFrame) return;

        this.isMuted = !this.isMuted;
        this.callFrame.setLocalAudio(!this.isMuted);

        this.elements.muteBtn.textContent = this.isMuted ? '🔇 Unmute' : '🎤 Mute';
        this.elements.muteBtn.classList.toggle('active', this.isMuted);
    }

    toggleSpeaker() {
        if (!this.callFrame) return;

        this.speakerEnabled = !this.speakerEnabled;

        // Get all remote participants
        const participants = this.callFrame.participants();
        Object.values(participants).forEach(participant => {
            if (participant.local) return;
            this.callFrame.updateParticipant(participant.session_id, {
                setAudio: this.speakerEnabled
            });
        });

        this.elements.speakerBtn.textContent = this.speakerEnabled ? '🔊 Speaker On' : '🔇 Speaker Off';
        this.elements.speakerBtn.classList.toggle('active', !this.speakerEnabled);
    }

    showConversationPanel() {
        this.elements.connectionPanel.style.display = 'none';
        this.elements.conversationPanel.style.display = 'block';
    }

    hideConversationPanel() {
        this.elements.connectionPanel.style.display = 'block';
        this.elements.conversationPanel.style.display = 'none';
    }

    setStatus(message, state) {
        this.elements.status.textContent = message;
        this.elements.status.className = 'status status-' + state;
    }

    updateCallStatus(status) {
        if (this.elements.callStatus) {
            this.elements.callStatus.textContent = status;
        }
    }

    updateLatency(ms) {
        if (this.elements.latency) {
            this.elements.latency.textContent = `${ms} ms`;
        }
    }

    updateSpeakingStatus(isSpeaking) {
        if (this.elements.speakingStatus) {
            this.elements.speakingStatus.textContent = isSpeaking ? 'Yes (HAL)' : 'No';
        }
    }

    setEyeState(state) {
        const eye = this.elements.halEye;

        // Remove all state classes
        eye.classList.remove('idle', 'listening', 'speaking', 'connecting', 'error');

        // Add current state
        eye.classList.add(state);
    }

    addTranscript(role, message) {
        const entry = {
            role: role,
            message: message,
            timestamp: new Date()
        };

        this.transcript.push(entry);

        // Add to DOM
        const div = document.createElement('div');
        div.className = `transcript-entry transcript-${role}`;

        const time = entry.timestamp.toLocaleTimeString();
        const roleLabel = role === 'user' ? 'You' : role === 'assistant' ? 'HAL' : 'System';

        div.innerHTML = `
            <span class="transcript-time">${time}</span>
            <span class="transcript-role">${roleLabel}:</span>
            <span class="transcript-message">${message}</span>
        `;

        this.elements.transcript.appendChild(div);

        // Scroll to bottom
        this.elements.transcript.scrollTop = this.elements.transcript.scrollHeight;
    }

    initVisualizer() {
        const canvas = this.elements.visualizer;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const width = canvas.width;
        const height = canvas.height;

        // Simple waveform animation
        const animate = () => {
            if (!this.isConnected) {
                // Draw flat line when not connected
                ctx.clearRect(0, 0, width, height);
                ctx.strokeStyle = '#ff0000';
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.moveTo(0, height / 2);
                ctx.lineTo(width, height / 2);
                ctx.stroke();
            } else {
                // Draw animated waveform when connected
                ctx.clearRect(0, 0, width, height);
                ctx.strokeStyle = '#ff0000';
                ctx.lineWidth = 2;
                ctx.beginPath();

                const time = Date.now() / 1000;
                for (let x = 0; x < width; x++) {
                    const y = height / 2 + Math.sin(x * 0.02 + time * 2) * 20 *
                             Math.sin(x * 0.005 + time * 0.5);
                    if (x === 0) {
                        ctx.moveTo(x, y);
                    } else {
                        ctx.lineTo(x, y);
                    }
                }
                ctx.stroke();
            }

            requestAnimationFrame(animate);
        };

        animate();
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.halClient = new HALWebRTCClient();
    console.log('HAL 9000 WebRTC Client initialized');
});

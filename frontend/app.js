// Configuration
const API_BASE_URL = window.location.hostname === 'localhost' ? 'http://localhost:5000' : '';

// DOM Elements - TTS Mode
const textInput = document.getElementById('textInput');
const charCount = document.getElementById('charCount');
const synthesizeBtn = document.getElementById('synthesizeBtn');
const randomQuoteBtn = document.getElementById('randomQuoteBtn');
const audioPlayerContainer = document.getElementById('audioPlayerContainer');
const audioPlayer = document.getElementById('audioPlayer');
const downloadBtn = document.getElementById('downloadBtn');
const status = document.getElementById('status');
const quotesList = document.getElementById('quotesList');
const halEye = document.getElementById('halEye');

// DOM Elements - Mode Toggle
const ttsModeBtn = document.getElementById('ttsMode');
const chatModeBtn = document.getElementById('chatMode');
const ttsPanel = document.getElementById('ttsPanel');
const chatPanel = document.getElementById('chatPanel');

// DOM Elements - Chat Mode
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const clearChatBtn = document.getElementById('clearChatBtn');
const micBtn = document.getElementById('micBtn');
const voiceStatus = document.getElementById('voiceStatus');
const continuousListeningCheckbox = document.getElementById('continuousListening');

// State
let currentAudioBlob = null;
let quotes = [];
let conversationHistory = [];
let currentMode = 'tts';
let recognition = null;
let isListening = false;
let isContinuousMode = false;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadQuotes();
    checkBackendHealth();
    setupModeToggle();
    setupChatHandlers();
    setupVoiceRecognition();
});

// Character counter
textInput.addEventListener('input', () => {
    const count = textInput.value.length;
    charCount.textContent = count;

    if (count > 900) {
        charCount.style.color = '#ffff00';
    } else {
        charCount.style.color = '#ff0000';
    }
});

// Synthesize speech
synthesizeBtn.addEventListener('click', async () => {
    const text = textInput.value.trim();

    if (!text) {
        updateStatus('Please enter text to synthesize.', 'error');
        return;
    }

    await synthesizeSpeech(text);
});

// Random quote
randomQuoteBtn.addEventListener('click', () => {
    if (quotes.length > 0) {
        const randomQuote = quotes[Math.floor(Math.random() * quotes.length)];
        textInput.value = randomQuote;
        textInput.dispatchEvent(new Event('input'));
    }
});

// Download audio
downloadBtn.addEventListener('click', () => {
    if (currentAudioBlob) {
        const url = URL.createObjectURL(currentAudioBlob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `hal9000_${Date.now()}.wav`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        updateStatus('Audio file downloaded.', 'success');
    }
});

// Functions
async function checkBackendHealth() {
    try {
        const response = await fetch(`${API_BASE_URL}/health`);
        const data = await response.json();

        if (data.status === 'operational') {
            updateStatus('System operational. All systems functional.', 'success');
        }
    } catch (error) {
        updateStatus('Warning: Backend server not responding. Please start the server.', 'error');
        synthesizeBtn.disabled = true;
    }
}

async function synthesizeSpeech(text) {
    try {
        updateStatus('Processing speech synthesis...', 'processing');
        activateEye(true);
        synthesizeBtn.disabled = true;

        const response = await fetch(`${API_BASE_URL}/api/synthesize`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ text }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Speech synthesis failed');
        }

        const audioBlob = await response.blob();
        currentAudioBlob = audioBlob;

        const audioUrl = URL.createObjectURL(audioBlob);
        audioPlayer.src = audioUrl;
        audioPlayerContainer.style.display = 'block';

        updateStatus('Speech synthesis complete. Ready to play.', 'success');

        // Auto-play the audio
        audioPlayer.play();

    } catch (error) {
        console.error('Error:', error);
        updateStatus(`Error: ${error.message}`, 'error');
    } finally {
        synthesizeBtn.disabled = false;
        activateEye(false);
    }
}

async function loadQuotes() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/quotes`);
        const data = await response.json();
        quotes = data.quotes;

        quotesList.innerHTML = quotes.map(quote => `
            <div class="quote-item" onclick="selectQuote('${quote.replace(/'/g, "\\'")}')">
                "${quote}"
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading quotes:', error);
    }
}

function selectQuote(quote) {
    textInput.value = quote;
    textInput.dispatchEvent(new Event('input'));
    textInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function updateStatus(message, type = 'info') {
    status.textContent = message;

    status.classList.remove('status-success', 'status-error', 'status-processing');

    if (type === 'success') {
        status.style.background = 'rgba(0, 255, 0, 0.1)';
        status.style.borderColor = '#00ff00';
        status.style.color = '#00ff00';
    } else if (type === 'error') {
        status.style.background = 'rgba(255, 0, 0, 0.1)';
        status.style.borderColor = '#ff0000';
        status.style.color = '#ff0000';
    } else if (type === 'processing') {
        status.style.background = 'rgba(255, 255, 0, 0.1)';
        status.style.borderColor = '#ffff00';
        status.style.color = '#ffff00';
    } else {
        status.style.background = 'rgba(255, 0, 0, 0.1)';
        status.style.borderColor = '#ff0000';
        status.style.color = '#ff0000';
    }
}

function activateEye(active) {
    if (active) {
        halEye.classList.add('active');
    } else {
        halEye.classList.remove('active');
    }
}

// Mode Toggle Functions
function setupModeToggle() {
    ttsModeBtn.addEventListener('click', () => {
        currentMode = 'tts';
        ttsModeBtn.classList.add('active');
        chatModeBtn.classList.remove('active');
        ttsPanel.style.display = 'block';
        chatPanel.style.display = 'none';
        updateStatus('TTS Mode active', 'info');
    });

    chatModeBtn.addEventListener('click', () => {
        currentMode = 'chat';
        chatModeBtn.classList.add('active');
        ttsModeBtn.classList.remove('active');
        chatPanel.style.display = 'block';
        ttsPanel.style.display = 'none';
        updateStatus('Chat Mode active - Ask HAL anything', 'info');
    });
}

// Chat Functions
function setupChatHandlers() {
    sendBtn.addEventListener('click', () => sendChatMessage());

    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });

    clearChatBtn.addEventListener('click', () => {
        conversationHistory = [];
        chatMessages.innerHTML = '<div class="system-message">Conversation cleared. HAL 9000 ready.</div>';
        updateStatus('Conversation history cleared', 'success');
    });
}

async function sendChatMessage() {
    const message = chatInput.value.trim();

    if (!message) {
        updateStatus('Please enter a message', 'error');
        return;
    }

    // Disable input while processing
    chatInput.disabled = true;
    sendBtn.disabled = true;
    activateEye(true);
    updateStatus('HAL is processing your query...', 'processing');

    // Add user message to chat
    addMessageToChat('user', message);

    // Clear input
    chatInput.value = '';

    try {
        const response = await fetch(`${API_BASE_URL}/api/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: message,
                history: conversationHistory
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Chat request failed');
        }

        const data = await response.json();

        // Add HAL's response to chat
        addMessageToChat('hal', data.response, data.audio_id);

        // Update conversation history
        conversationHistory.push({
            role: 'user',
            content: message
        });
        conversationHistory.push({
            role: 'assistant',
            content: data.response
        });

        updateStatus('HAL has responded', 'success');

    } catch (error) {
        console.error('Error:', error);
        updateStatus(`Error: ${error.message}`, 'error');
        addMessageToChat('system', `Error: ${error.message}`);
    } finally {
        chatInput.disabled = false;
        sendBtn.disabled = false;
        activateEye(false);
        chatInput.focus();
    }
}

function addMessageToChat(type, content, audioId = null) {
    const messageDiv = document.createElement('div');

    if (type === 'user') {
        messageDiv.className = 'message user-message';
        messageDiv.innerHTML = `
            <div class="message-header">YOU</div>
            <div class="message-content">${escapeHtml(content)}</div>
        `;
    } else if (type === 'hal') {
        messageDiv.className = 'message hal-message';
        messageDiv.innerHTML = `
            <div class="message-header">HAL 9000</div>
            <div class="message-content">${escapeHtml(content)}</div>
            ${audioId ? `
                <div class="message-audio">
                    <audio controls autoplay>
                        <source src="${API_BASE_URL}/api/audio/${audioId}" type="audio/wav">
                    </audio>
                </div>
            ` : ''}
        `;
    } else if (type === 'system') {
        messageDiv.className = 'system-message';
        messageDiv.textContent = content;
    }

    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Voice Recognition Setup
function setupVoiceRecognition() {
    // Check if browser supports speech recognition
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        console.warn('Speech recognition not supported in this browser');
        micBtn.disabled = true;
        micBtn.title = 'Speech recognition not supported';
        return;
    }

    // Initialize speech recognition
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    // Handle recognition results
    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        console.log('Recognized:', transcript);

        // Put transcript in input field
        chatInput.value = transcript;

        // Auto-send in continuous mode
        if (isContinuousMode) {
            sendChatMessage();
        }
    };

    // Handle recognition errors
    recognition.onerror = (event) => {
        console.error('Recognition error:', event.error);
        stopListening();

        if (event.error === 'no-speech') {
            updateStatus('No speech detected. Try again.', 'error');
        } else if (event.error === 'not-allowed') {
            updateStatus('Microphone access denied. Please allow microphone access.', 'error');
            micBtn.disabled = true;
        } else {
            updateStatus(`Voice recognition error: ${event.error}`, 'error');
        }
    };

    // Handle recognition end
    recognition.onend = () => {
        if (isContinuousMode && isListening) {
            // Restart in continuous mode
            try {
                recognition.start();
            } catch (e) {
                console.error('Failed to restart recognition:', e);
                stopListening();
            }
        } else {
            stopListening();
        }
    };

    // Microphone button click handler
    micBtn.addEventListener('click', () => {
        if (isListening) {
            stopListening();
        } else {
            startListening();
        }
    });

    // Continuous listening toggle
    continuousListeningCheckbox.addEventListener('change', (e) => {
        isContinuousMode = e.target.checked;

        if (isContinuousMode && !isListening) {
            updateStatus('Continuous listening mode enabled. Click microphone to start.', 'info');
        } else if (!isContinuousMode && isListening) {
            // Switch to push-to-talk mode
            updateStatus('Push-to-talk mode enabled', 'info');
        }
    });

    // Keyboard shortcut: Hold spacebar to talk (when in chat mode)
    document.addEventListener('keydown', (e) => {
        if (e.code === 'Space' && currentMode === 'chat' && !chatInput.matches(':focus') && !isListening) {
            e.preventDefault();
            startListening();
        }
    });

    document.addEventListener('keyup', (e) => {
        if (e.code === 'Space' && currentMode === 'chat' && isListening && !isContinuousMode) {
            e.preventDefault();
            stopListening();
        }
    });
}

function startListening() {
    if (!recognition) return;

    try {
        isListening = true;
        micBtn.classList.add('listening');
        voiceStatus.style.display = 'block';
        voiceStatus.textContent = isContinuousMode ? 'Listening continuously...' : 'Listening...';
        activateEye(true);

        recognition.start();
        updateStatus('Listening... Speak now.', 'processing');
    } catch (e) {
        console.error('Failed to start recognition:', e);
        stopListening();
        updateStatus('Could not start voice recognition', 'error');
    }
}

function stopListening() {
    if (!recognition) return;

    isListening = false;
    micBtn.classList.remove('listening');
    voiceStatus.style.display = 'none';
    activateEye(false);

    try {
        recognition.stop();
    } catch (e) {
        // Already stopped
    }

    if (!isContinuousMode) {
        updateStatus('Voice input stopped', 'info');
    }
}

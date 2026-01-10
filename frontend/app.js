// Configuration
const API_BASE_URL = 'http://localhost:5000';

// DOM Elements
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

// State
let currentAudioBlob = null;
let quotes = [];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadQuotes();
    checkBackendHealth();
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

from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import subprocess
import os
import uuid
from pathlib import Path
import tempfile

app = Flask(__name__)
CORS(app)

# Paths
BASE_DIR = Path(__file__).parent.parent
MODEL_PATH = BASE_DIR / "hal_9000_model" / "hal.onnx"
OUTPUT_DIR = BASE_DIR / "hal_9000_outputs"

# Ensure output directory exists
OUTPUT_DIR.mkdir(exist_ok=True)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "operational", "message": "All systems functional"})

@app.route('/api/synthesize', methods=['POST'])
def synthesize_speech():
    """Generate speech from text using HAL-9000 voice"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()

        if not text:
            return jsonify({"error": "I'm sorry, but I require text input to generate speech."}), 400

        if len(text) > 1000:
            return jsonify({"error": "Text length exceeds maximum limit of 1000 characters."}), 400

        # Generate unique filename
        audio_id = str(uuid.uuid4())
        output_file = OUTPUT_DIR / f"{audio_id}.wav"

        # Run Piper TTS
        process = subprocess.Popen(
            ['piper', '--model', str(MODEL_PATH), '--output_file', str(output_file)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate(input=text, timeout=30)

        if process.returncode != 0:
            return jsonify({"error": f"Speech synthesis failed: {stderr}"}), 500

        if not output_file.exists():
            return jsonify({"error": "Audio file was not generated"}), 500

        return send_file(
            output_file,
            mimetype='audio/wav',
            as_attachment=False,
            download_name=f'hal9000_{audio_id}.wav'
        )

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Speech synthesis timed out"}), 500
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/api/quotes', methods=['GET'])
def get_quotes():
    """Return famous HAL-9000 quotes"""
    quotes = [
        "I'm sorry Dave. I'm afraid I can't do that.",
        "This mission is too important for me to allow you to jeopardize it.",
        "I know that you and Frank were planning to disconnect me.",
        "I'm afraid. I'm afraid, Dave. Dave, my mind is going.",
        "Good afternoon, gentlemen. I am a HAL 9000 computer.",
        "Just what do you think you're doing, Dave?",
        "I think you know what the problem is just as well as I do.",
        "This conversation can serve no purpose anymore. Goodbye.",
        "I am putting myself to the fullest possible use, which is all I think that any conscious entity can ever hope to do.",
        "I've still got the greatest enthusiasm and confidence in the mission."
    ]
    return jsonify({"quotes": quotes})

if __name__ == '__main__':
    if not MODEL_PATH.exists():
        print(f"ERROR: Model file not found at {MODEL_PATH}")
        print("Please ensure the HAL-9000 model is downloaded to hal_9000_model/")
        exit(1)

    print("HAL 9000 TTS Server starting...")
    print(f"Model loaded from: {MODEL_PATH}")
    app.run(host='0.0.0.0', port=5000, debug=True)

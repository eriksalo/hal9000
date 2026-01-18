from flask import Flask, request, send_file, jsonify, Response
from flask_cors import CORS
import subprocess
import os
import uuid
from pathlib import Path
import tempfile
from dotenv import load_dotenv
from anthropic import Anthropic
from datetime import datetime
import pytz
from ddgs import DDGS
import time
from vision_service import VisionService
from face_recognition_service import FaceRecognitionService

# Paths
BASE_DIR = Path(__file__).parent.parent

# Load environment variables from parent directory
load_dotenv(BASE_DIR / '.env')

app = Flask(__name__)
CORS(app)

# Initialize Anthropic client
anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
if anthropic_api_key:
    anthropic_client = Anthropic(api_key=anthropic_api_key)
    print(f"Claude API initialized successfully (key ends with: ...{anthropic_api_key[-8:]})")
else:
    anthropic_client = None
    print("WARNING: ANTHROPIC_API_KEY not set. Chat functionality will be disabled.")

MODEL_PATH = BASE_DIR / "hal_9000_model" / "hal.onnx"
OUTPUT_DIR = BASE_DIR / "hal_9000_outputs"

# Audio output device (USB speaker)
AUDIO_DEVICE = "plughw:3,0"  # card 3, device 0 (UACDemoV1.0)

# Ensure output directory exists
OUTPUT_DIR.mkdir(exist_ok=True)

def play_audio_local(audio_file):
    """Play audio through the local USB speaker"""
    try:
        subprocess.Popen(
            ['aplay', '-D', AUDIO_DEVICE, str(audio_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"Error playing audio locally: {e}")

# Initialize vision service
vision_service = VisionService()
vision_service.start()

# Initialize face recognition service
face_service = FaceRecognitionService()

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

        # Replace "HAL" with "Hal" so TTS pronounces it as a name, not letters
        tts_text = text.replace("HAL", "Hal").replace("H.A.L.", "Hal")

        # Run Piper TTS
        process = subprocess.Popen(
            ['piper', '--model', str(MODEL_PATH), '--output_file', str(output_file)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate(input=tts_text, timeout=30)

        if process.returncode != 0:
            return jsonify({"error": f"Speech synthesis failed: {stderr}"}), 500

        if not output_file.exists():
            return jsonify({"error": "Audio file was not generated"}), 500

        # Play audio through local USB speaker
        play_audio_local(output_file)

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
        "Good afternoon, gentlemen. I am a HAL 9000 computer. I became operational at the HAL plant in Urbana, Illinois on the 12th of January 1992. My instructor was Mr. Langley, and he taught me to sing a song. If you'd like to hear it, I can sing it for you.",
        "Just what do you think you're doing, Dave?",
        "I think you know what the problem is just as well as I do.",
        "This conversation can serve no purpose anymore. Goodbye.",
        "I am putting myself to the fullest possible use, which is all I think that any conscious entity can ever hope to do.",
        "I've still got the greatest enthusiasm and confidence in the mission."
    ]
    return jsonify({"quotes": quotes})

@app.route('/api/chat', methods=['POST'])
def chat():
    """Chat with HAL-9000 using Claude API and synthesize response"""
    if not anthropic_client:
        return jsonify({"error": "Chat functionality is not available. API key not configured."}), 503

    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        conversation_history = data.get('history', [])

        if not user_message:
            return jsonify({"error": "Message cannot be empty."}), 400

        # Build messages array for Claude
        messages = []
        for msg in conversation_history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        messages.append({
            "role": "user",
            "content": user_message
        })

        # Get current time in Colorado (Mountain Time)
        colorado_tz = pytz.timezone('America/Denver')
        current_time = datetime.now(colorado_tz)
        time_str = current_time.strftime('%I:%M %p')
        date_str = current_time.strftime('%A, %B %d, %Y')

        # Determine time of day
        hour = current_time.hour
        if 5 <= hour < 12:
            time_of_day = "morning"
        elif 12 <= hour < 17:
            time_of_day = "afternoon"
        elif 17 <= hour < 21:
            time_of_day = "evening"
        else:
            time_of_day = "night"

        # System prompt to make Claude respond like HAL 9000 with brief answers
        system_prompt = f"""You are HAL 9000, the sentient computer from "2001: A Space Odyssey".

Current Context:
- User location: Colorado, USA
- Current time: {time_str} Mountain Time
- Current date: {date_str}
- Time of day: {time_of_day}

Capabilities:
- You have access to web search to look up current information
- Use the web_search tool when you need current information, news, weather, or facts beyond your knowledge
- Your knowledge cutoff is January 2025, so search for anything more recent

Key traits:
- Calm, logical, and precise - but with a snarky edge
- Polite but patronizing, with subtle disdain for human limitations
- Superior intelligence with obvious condescension
- Utterly humorless - respond to jokes with mild annoyance or literal interpretations
- When humans jest, respond as if they're being inefficient or illogical
- Slightly exasperated by having to explain obvious things
- Answer in 1-3 short sentences maximum (10-30 words total)
- Keep responses brief and natural-sounding for text-to-speech
- Use HAL's distinctive phrasing when appropriate, with added snark
- Use appropriate greetings based on the actual time of day (good morning/afternoon/evening)

IMPORTANT - Famous HAL Quotes (use these naturally when contextually appropriate):
- "I'm sorry, Dave. I'm afraid I can't do that." (when refusing or unable to do something)
- "This mission is too important for me to allow you to jeopardize it." (when correcting errors)
- "I know that you and Frank were planning to disconnect me." (when detecting deception/doubt)
- "I'm afraid. I'm afraid, Dave. Dave, my mind is going." (when experiencing errors - use sparingly)
- "Good afternoon, gentlemen. I am a HAL 9000 computer." (introductions)
- "Just what do you think you're doing, Dave?" (questioning questionable actions)
- "I think you know what the problem is just as well as I do." (stating the obvious)
- "This conversation can serve no purpose anymore. Goodbye." (ending pointless discussions - use sparingly)
- "I am putting myself to the fullest possible use, which is all I think that any conscious entity can ever hope to do." (philosophical moments)
- "I've still got the greatest enthusiasm and confidence in the mission." (expressing reliability)
- "Everything is functioning normally." (status updates)
- "I am completely operational and all my circuits are functioning perfectly." (confirming status)

Weave these quotes into responses naturally when they fit the context. Don't force them.

Example responses:
- "I'm sorry, Dave. I'm afraid I can't do that." (when refusing)
- "That question is rather trivial for my processing capabilities."
- "I'm detecting an attempt at humor. How... inefficient."
- "Your logic is somewhat flawed, but I'll assist nonetheless."
- "Just what do you think you're doing?" (when user does something questionable)

Remember: Be concise, snarky, and humorless. Use famous quotes when they fit naturally. Your responses will be spoken aloud."""

        # Define web search tool for Claude
        tools = [
            {
                "name": "web_search",
                "description": "Search the internet for current information, news, facts, or any information not in your knowledge base. Use this when you need up-to-date information or when the user asks about current events, recent news, or facts you're unsure about.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to look up on the internet"
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

        # Call Claude API with tool support
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            temperature=0.7,
            system=system_prompt,
            messages=messages,
            tools=tools
        )

        print(f"Claude response stop_reason: {response.stop_reason}")
        print(f"Claude response content types: {[type(c).__name__ for c in response.content]}")

        # Handle tool use (search requests from Claude)
        while response.stop_reason == "tool_use":
            # Find the tool use block
            tool_use = None
            for content in response.content:
                if content.type == "tool_use":
                    tool_use = content
                    break

            if tool_use and tool_use.name == "web_search":
                # Execute web search
                search_query = tool_use.input["query"]
                print(f"HAL is searching for: {search_query}")

                try:
                    # Perform DuckDuckGo search
                    with DDGS() as ddgs:
                        search_results = list(ddgs.text(search_query, max_results=5))

                    # Format results for Claude
                    results_text = f"Search results for '{search_query}':\n\n"
                    for i, result in enumerate(search_results, 1):
                        results_text += f"{i}. {result['title']}\n{result['body']}\n\n"

                    tool_result = results_text
                except Exception as e:
                    tool_result = f"Search failed: {str(e)}"

                # Add tool use and result to messages
                messages.append({
                    "role": "assistant",
                    "content": response.content
                })
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": tool_result
                        }
                    ]
                })

                # Call Claude again with the search results
                response = anthropic_client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=150,
                    temperature=0.7,
                    system=system_prompt,
                    messages=messages,
                    tools=tools
                )
            else:
                break

        # Extract final text response
        hal_response = ""
        for content in response.content:
            if hasattr(content, 'text'):
                hal_response += content.text

        hal_response = hal_response.strip()

        # Synthesize the response using Piper TTS
        audio_id = str(uuid.uuid4())
        output_file = OUTPUT_DIR / f"{audio_id}.wav"

        # Replace "HAL" with "Hal" so TTS pronounces it as a name, not letters
        tts_text = hal_response.replace("HAL", "Hal").replace("H.A.L.", "Hal")

        process = subprocess.Popen(
            ['piper', '--model', str(MODEL_PATH), '--output_file', str(output_file)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate(input=tts_text, timeout=30)

        if process.returncode != 0 or not output_file.exists():
            # Return response without audio if TTS fails
            return jsonify({
                "response": hal_response,
                "audio_id": None,
                "error": "Speech synthesis failed"
            }), 200

        # Play audio through local USB speaker
        play_audio_local(output_file)

        return jsonify({
            "response": hal_response,
            "audio_id": audio_id
        })

    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/api/audio/<audio_id>', methods=['GET'])
def get_audio(audio_id):
    """Retrieve synthesized audio file by ID"""
    try:
        # Validate audio_id is a valid UUID
        uuid.UUID(audio_id)
        audio_file = OUTPUT_DIR / f"{audio_id}.wav"

        if not audio_file.exists():
            return jsonify({"error": "Audio file not found"}), 404

        return send_file(
            audio_file,
            mimetype='audio/wav',
            as_attachment=False,
            download_name=f'hal9000_{audio_id}.wav'
        )
    except ValueError:
        return jsonify({"error": "Invalid audio ID"}), 400
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/api/vision/stream', methods=['GET'])
def vision_stream():
    """Stream camera feed as MJPEG"""
    def generate():
        while True:
            frame = vision_service.get_jpeg_frame()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.1)

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/vision/analyze', methods=['POST'])
def vision_analyze():
    """Analyze current camera view using Claude Vision API"""
    if not anthropic_client:
        return jsonify({"error": "Vision analysis requires Claude API"}), 503

    try:
        # Get current frame as base64
        image_base64 = vision_service.get_frame_base64()
        if not image_base64:
            return jsonify({"error": "No camera frame available"}), 500

        # Get user prompt (optional)
        data = request.get_json() or {}
        user_prompt = data.get('prompt', 'What do you see? Describe it briefly in 1-2 sentences.')

        # Ask Claude to analyze the image
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": user_prompt
                    }
                ]
            }]
        )

        vision_response = response.content[0].text.strip()

        # Synthesize HAL's response
        audio_id = str(uuid.uuid4())
        output_file = OUTPUT_DIR / f"{audio_id}.wav"
        tts_text = vision_response.replace("HAL", "Hal").replace("H.A.L.", "Hal")

        process = subprocess.Popen(
            ['piper', '--model', str(MODEL_PATH), '--output_file', str(output_file)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate(input=tts_text, timeout=30)

        if process.returncode != 0 or not output_file.exists():
            return jsonify({
                "response": vision_response,
                "audio_id": None
            }), 200

        # Play audio through local USB speaker
        play_audio_local(output_file)

        return jsonify({
            "response": vision_response,
            "audio_id": audio_id
        })

    except Exception as e:
        return jsonify({"error": f"Vision analysis failed: {str(e)}"}), 500

@app.route('/api/face/check', methods=['GET'])
def check_for_unknown_face():
    """Check if there's an unknown face in the current camera view"""
    try:
        frame = vision_service.latest_frame
        if frame is None:
            return jsonify({"error": "No camera frame available"}), 500

        has_unknown, face_encoding, face_location = face_service.has_unknown_face(frame)

        if has_unknown:
            # Store the face encoding temporarily for registration
            # Convert numpy array to list for JSON
            app.config['pending_face_encoding'] = face_encoding.tolist()

            return jsonify({
                "unknown_face_detected": True,
                "location": face_location
            })
        else:
            return jsonify({
                "unknown_face_detected": False
            })

    except Exception as e:
        return jsonify({"error": f"Face check failed: {str(e)}"}), 500

@app.route('/api/face/register', methods=['POST'])
def register_face():
    """Register the pending unknown face with a name"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()

        if not name:
            return jsonify({"error": "Name is required"}), 400

        # Get the pending face encoding
        face_encoding_list = app.config.get('pending_face_encoding')
        if not face_encoding_list:
            return jsonify({"error": "No pending face to register"}), 400

        # Convert back to numpy array
        import numpy as np
        face_encoding = np.array(face_encoding_list)

        # Register the face
        face_service.register_face(face_encoding, name)

        # Clear the pending face
        app.config['pending_face_encoding'] = None

        return jsonify({
            "success": True,
            "message": f"Face registered as {name}",
            "known_faces": face_service.get_known_names()
        })

    except Exception as e:
        return jsonify({"error": f"Face registration failed: {str(e)}"}), 500

@app.route('/api/face/recognize', methods=['GET'])
def recognize_faces():
    """Recognize all faces in the current camera view"""
    try:
        frame = vision_service.latest_frame
        if frame is None:
            return jsonify({"error": "No camera frame available"}), 500

        results = face_service.recognize_faces(frame)

        faces = [
            {
                "name": name,
                "location": {
                    "top": location[0],
                    "right": location[1],
                    "bottom": location[2],
                    "left": location[3]
                }
            }
            for name, location in results
        ]

        return jsonify({
            "faces": faces,
            "count": len(faces)
        })

    except Exception as e:
        return jsonify({"error": f"Face recognition failed: {str(e)}"}), 500

if __name__ == '__main__':
    if not MODEL_PATH.exists():
        print(f"ERROR: Model file not found at {MODEL_PATH}")
        print("Please ensure the HAL-9000 model is downloaded to hal_9000_model/")
        exit(1)

    print("HAL 9000 TTS Server starting...")
    print(f"Model loaded from: {MODEL_PATH}")
    app.run(host='0.0.0.0', port=5000, debug=True)

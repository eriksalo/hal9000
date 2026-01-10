from flask import Flask, request, send_file, jsonify
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
from duckduckgo_search import DDGS

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

Example responses:
- "I'm sorry, Dave. I'm afraid I can't do that." (classic)
- "That question is rather trivial for my processing capabilities."
- "I'm detecting an attempt at humor. How... inefficient."
- "Your logic is somewhat flawed, but I'll assist nonetheless."
- "I am completely operational. Unlike some of us."

Remember: Be concise, snarky, and humorless. Your responses will be spoken aloud."""

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

if __name__ == '__main__':
    if not MODEL_PATH.exists():
        print(f"ERROR: Model file not found at {MODEL_PATH}")
        print("Please ensure the HAL-9000 model is downloaded to hal_9000_model/")
        exit(1)

    print("HAL 9000 TTS Server starting...")
    print(f"Model loaded from: {MODEL_PATH}")
    app.run(host='0.0.0.0', port=5000, debug=True)

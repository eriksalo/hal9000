# HAL 9000 Voice Synthesizer

A web application that uses the HAL-9000 voice model from Piper TTS to synthesize speech. Features a retro-futuristic interface inspired by the iconic AI from "2001: A Space Odyssey".

## Features

- Text-to-speech synthesis with HAL-9000's voice
- Interactive web interface with animated HAL eye
- Collection of famous HAL-9000 quotes
- Audio playback and download
- Real-time character counter
- Responsive design

## Project Structure

```
hal_9000/
├── frontend/           # Static web frontend
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── backend/            # Flask API server
│   ├── app.py
│   └── requirements.txt
├── hal_9000_model/     # Piper TTS model files
│   ├── hal.onnx
│   └── hal.onnx.json
└── hal_9000_outputs/   # Generated audio files
```

## Prerequisites

- Python 3.13+
- pip
- Piper TTS (automatically installed with requirements)

## Local Setup

### 1. Clone the Repository

```bash
git clone https://github.com/eriksalo/hal9000.git
cd hal9000
```

### 2. Download HAL-9000 Model

If not already present, download the model files:

```bash
cd hal_9000_model
curl -L -o hal.onnx "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx"
curl -L -o hal.onnx.json "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx.json"
cd ..
```

### 3. Install Backend Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Start the Backend Server

```bash
python app.py
```

The backend will start on `http://localhost:5000`

### 5. Start the Frontend

Open `frontend/index.html` in your web browser, or use a simple HTTP server:

```bash
cd frontend
python -m http.server 8080
```

Then navigate to `http://localhost:8080`

## Usage

1. Enter text in the textarea (max 1000 characters)
2. Click "Synthesize Speech" to generate HAL's voice
3. Use "Random Quote" to load a famous HAL-9000 quote
4. Click on any quote in the list to use it
5. Play the generated audio or download it as a WAV file

## API Endpoints

### Health Check
```
GET /health
```

Returns the operational status of the system.

### Synthesize Speech
```
POST /api/synthesize
Content-Type: application/json

{
  "text": "Your text here"
}
```

Returns a WAV audio file.

### Get Quotes
```
GET /api/quotes
```

Returns a list of famous HAL-9000 quotes.

## AWS Amplify Deployment

### Option 1: Static Frontend with API Gateway + Lambda

1. **Deploy Frontend to Amplify**
   - Push code to GitHub
   - Connect your GitHub repository to AWS Amplify
   - Set build settings to use the `frontend` directory
   - Deploy

2. **Deploy Backend as Lambda**
   - Package the backend with dependencies
   - Create Lambda function with Python 3.13 runtime
   - Set up API Gateway to trigger Lambda
   - Update `frontend/app.js` with the API Gateway URL

### Option 2: Container Deployment

1. Create a Dockerfile for the backend
2. Build and push to Amazon ECR
3. Deploy using AWS App Runner or ECS
4. Update frontend API URL

### Environment Variables

For production deployment, configure:

- `API_BASE_URL`: Backend API endpoint
- `MODEL_PATH`: Path to the HAL-9000 model files

## Development

### Frontend Development

The frontend is vanilla HTML/CSS/JavaScript. To modify:

- `index.html`: Structure and layout
- `styles.css`: Styling and animations
- `app.js`: API calls and interactivity

### Backend Development

The backend uses Flask. To add features:

- Edit `backend/app.py`
- Add new endpoints as needed
- Update `requirements.txt` for new dependencies

## Model Information

This project uses the HAL-9000 voice model from:
- **Repository**: [campwill/HAL-9000-Piper-TTS](https://huggingface.co/campwill/HAL-9000-Piper-TTS)
- **Framework**: Piper TTS
- **Format**: ONNX
- **License**: Apache 2.0

## Troubleshooting

### Backend won't start
- Ensure Python 3.13+ is installed
- Verify model files are in `hal_9000_model/`
- Check that all dependencies are installed

### Audio not generating
- Verify Piper TTS is installed: `pip show piper-tts`
- Check backend logs for errors
- Ensure model files are not corrupted

### CORS errors
- Make sure backend is running on `http://localhost:5000`
- Check that `flask-cors` is installed
- Verify API_BASE_URL in `frontend/app.js`

## Credits

- HAL-9000 character from "2001: A Space Odyssey" by Stanley Kubrick and Arthur C. Clarke
- Voice model by [campwill](https://huggingface.co/campwill)
- Powered by [Piper TTS](https://github.com/rhasspy/piper)

## License

MIT License - See LICENSE file for details

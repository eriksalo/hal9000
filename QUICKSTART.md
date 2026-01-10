# Quick Start Guide

## Local Development

### 1. Start the Backend

```bash
cd backend
python app.py
```

The backend will start on `http://localhost:5000`

### 2. Open the Frontend

Simply open `frontend/index.html` in your web browser:

```bash
# On Windows
start frontend/index.html

# Or use a simple HTTP server
cd frontend
python -m http.server 8080
```

Then navigate to `http://localhost:8080`

### 3. Test the Application

1. Enter text in the textarea or click "Random Quote"
2. Click "Synthesize Speech"
3. Listen to HAL's voice!
4. Download the audio if desired

## AWS Amplify Deployment

### Quick Deploy (Frontend Only)

1. **Push to GitHub** (Already done! ✓)
   ```
   https://github.com/eriksalo/hal9000
   ```

2. **Connect to AWS Amplify**
   - Go to https://console.aws.amazon.com/amplify/
   - Click "New app" → "Host web app"
   - Connect GitHub repository: `eriksalo/hal9000`
   - Select branch: `main`
   - Click "Save and deploy"

3. **Note**: The frontend will be deployed, but you'll need to deploy the backend separately (see DEPLOYMENT.md)

### Backend Deployment Options

See `DEPLOYMENT.md` for detailed instructions on:
- AWS Lambda + API Gateway
- AWS App Runner (recommended)
- EC2 Instance

## Testing

✓ Backend is working - health check passed
✓ TTS synthesis working - test audio generated
✓ All endpoints operational

## Features

- 🎙️ Text-to-Speech with HAL-9000 voice
- 👁️ Animated HAL eye interface
- 💬 10 famous HAL-9000 quotes
- 🎵 Audio playback and download
- 📝 1000 character limit with counter
- 🌐 RESTful API

## API Endpoints

```
GET  /health              - Health check
POST /api/synthesize      - Generate speech
GET  /api/quotes          - Get HAL quotes
```

## Tech Stack

**Frontend:**
- HTML5
- CSS3 (with animations)
- Vanilla JavaScript

**Backend:**
- Python 3.13
- Flask 3.0
- Piper TTS 1.3
- Flask-CORS

**Model:**
- HAL-9000 Piper TTS (ONNX format)
- 61MB model size

## Next Steps

1. Deploy backend to AWS (see DEPLOYMENT.md)
2. Update `frontend/app.js` with production API URL
3. Set up custom domain (optional)
4. Configure SSL/HTTPS
5. Add monitoring and analytics

## Troubleshooting

### Backend won't start
```bash
pip install -r backend/requirements.txt
```

### Frontend can't connect
- Ensure backend is running on port 5000
- Check browser console for CORS errors
- Verify API_BASE_URL in `frontend/app.js`

### No audio generated
- Verify model files in `hal_9000_model/`
- Check backend logs for errors
- Ensure Piper TTS is installed

## Support

For issues or questions:
- Check README.md for detailed documentation
- See DEPLOYMENT.md for AWS setup
- GitHub: https://github.com/eriksalo/hal9000

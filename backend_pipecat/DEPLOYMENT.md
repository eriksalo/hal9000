# HAL 9000 Pipecat - Deployment Guide

Deploy HAL 9000 Pipecat backend to production environments.

## Table of Contents

1. [Raspberry Pi Deployment](#raspberry-pi-deployment)
2. [Cloud Deployment](#cloud-deployment)
3. [Docker Deployment](#docker-deployment)
4. [Monitoring & Logs](#monitoring--logs)
5. [Troubleshooting](#troubleshooting)

---

## Raspberry Pi Deployment

### Prerequisites

- Raspberry Pi 5 (recommended) or Pi 4 with 4GB+ RAM
- Raspberry Pi OS (64-bit)
- Pi Camera Module 3 (optional, for face recognition)
- USB microphone and speakers
- Internet connection

### Installation

```bash
# 1. Clone repository
git clone https://github.com/eriksalo/hal9000.git
cd hal9000

# 2. Run setup script
chmod +x setup_pi.sh
./setup_pi.sh

# 3. Install Pipecat dependencies
cd backend_pipecat
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
nano .env
# Set ANTHROPIC_API_KEY and other settings
```

### Systemd Service

Run HAL as a system service that starts on boot:

```bash
# 1. Copy service file
sudo cp hal-pipecat.service /etc/systemd/system/

# 2. Reload systemd
sudo systemctl daemon-reload

# 3. Enable service (start on boot)
sudo systemctl enable hal-pipecat

# 4. Start service
sudo systemctl start hal-pipecat

# 5. Check status
sudo systemctl status hal-pipecat

# 6. View logs
sudo journalctl -u hal-pipecat -f
```

### Service Management

```bash
# Start HAL
sudo systemctl start hal-pipecat

# Stop HAL
sudo systemctl stop hal-pipecat

# Restart HAL
sudo systemctl restart hal-pipecat

# Check status
sudo systemctl status hal-pipecat

# View logs (real-time)
sudo journalctl -u hal-pipecat -f

# View logs (last 100 lines)
sudo journalctl -u hal-pipecat -n 100

# Disable auto-start
sudo systemctl disable hal-pipecat
```

### Performance Tuning

For Raspberry Pi, optimize for lower latency:

```bash
# Edit .env
USE_VOSK=1              # Use Vosk (faster than Whisper)
USE_HTTP_TTS=1          # Use Flask TTS endpoint
MIC_GAIN=20             # Increase if needed
CAMERA_FPS=10           # Lower FPS for better CPU usage
```

### Hardware Setup

**Audio Configuration:**

```bash
# List audio devices
arecord -l
aplay -l

# Set in .env
AUDIO_INPUT_DEVICE=plughw:CARD=CMTECK,DEV=0
AUDIO_OUTPUT_DEVICE=default

# Test microphone
arecord -D plughw:CARD=CMTECK,DEV=0 -f S16_LE -r 16000 -d 3 test.wav
aplay test.wav
```

**Camera Configuration:**

```bash
# Test Pi Camera
libcamera-hello --list-cameras
libcamera-still -o test.jpg

# Set in .env
CAMERA_TYPE=picamera2
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_FPS=10
```

---

## Cloud Deployment

### AWS Deployment

#### Option 1: EC2 Instance

```bash
# 1. Launch EC2 instance
# - AMI: Ubuntu 22.04 LTS
# - Instance type: t3.medium or better
# - Storage: 20GB+

# 2. Install dependencies
sudo apt update
sudo apt install -y python3-pip git portaudio19-dev

# 3. Clone and setup
git clone https://github.com/eriksalo/hal9000.git
cd hal9000/backend_pipecat
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
nano .env
# Set ANTHROPIC_API_KEY and DAILY_ROOM_URL

# 5. Run with systemd (same as Pi deployment)
```

#### Option 2: ECS/Fargate (Docker)

See [Docker Deployment](#docker-deployment) section.

### Digital Ocean Deployment

```bash
# 1. Create Droplet
# - Image: Ubuntu 22.04
# - Size: Basic (2 vCPUs, 4GB RAM)

# 2. SSH and install
ssh root@your-droplet-ip
apt update && apt upgrade -y
apt install -y python3-pip git

# 3. Setup HAL (same as EC2)
```

### Heroku Deployment

```bash
# 1. Create Procfile
echo "web: python hal_pipeline.py" > Procfile

# 2. Create requirements.txt
# (already exists in backend_pipecat/)

# 3. Deploy
heroku create hal9000-pipecat
heroku config:set ANTHROPIC_API_KEY=your_key
git push heroku main

# Note: Requires Daily.co for WebRTC audio
```

---

## Docker Deployment

### Dockerfile

```dockerfile
# backend_pipecat/Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Copy models (or mount as volume)
# COPY ../hal_9000_model /app/hal_9000_model
# COPY ../vosk_model /app/vosk_model

# Environment
ENV PYTHONUNBUFFERED=1

# Run HAL
CMD ["python", "hal_autonomous.py"]
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  hal-backend:
    build: ./backend
    ports:
      - "5000:5000"
    environment:
      - FLASK_ENV=production
    volumes:
      - ./hal_9000_model:/app/hal_9000_model
      - ./hal_9000_outputs:/app/hal_9000_outputs

  hal-pipecat:
    build: ./backend_pipecat
    depends_on:
      - hal-backend
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - FLASK_BASE_URL=http://hal-backend:5000
      - USE_VOSK=1
      - USE_HTTP_TTS=1
    volumes:
      - ./hal_9000_model:/app/hal_9000_model
      - ./vosk_model:/app/vosk_model
      - ./memory:/app/memory
    devices:
      - /dev/snd:/dev/snd  # Audio devices
      - /dev/video0:/dev/video0  # Camera (optional)
```

### Running with Docker

```bash
# Build
docker-compose build

# Run
docker-compose up -d

# View logs
docker-compose logs -f hal-pipecat

# Stop
docker-compose down
```

---

## Monitoring & Logs

### Log Files

```bash
# Application logs
tail -f /home/erik/hal9000/backend_pipecat/hal_autonomous.log

# Flask backend logs
tail -f /home/erik/hal9000/backend/hal9000.log

# System logs (systemd)
sudo journalctl -u hal-pipecat -f
```

### Health Checks

```bash
# Check Flask backend
curl http://localhost:5000/health

# Check Pipecat status
sudo systemctl status hal-pipecat

# Check memory usage
free -h

# Check CPU usage
htop
```

### Metrics

Monitor these metrics for production:

- **Response latency**: Time from speech end to TTS start
- **Memory usage**: Should stay under 2GB
- **CPU usage**: 50-100% during conversations
- **API calls**: Track Anthropic API usage
- **Face detection FPS**: 5-10 FPS typical

### Alerting

Set up alerts for:

- Service crashes (systemd failures)
- High memory usage (>90%)
- API errors (4xx, 5xx responses)
- No face detection for extended periods

---

## Troubleshooting

### Service Won't Start

```bash
# Check logs
sudo journalctl -u hal-pipecat -n 100

# Check environment
sudo systemctl show hal-pipecat | grep Environment

# Check permissions
ls -la /home/erik/hal9000/backend_pipecat/
```

### Audio Issues

```bash
# Verify audio devices
arecord -l
aplay -l

# Test microphone
arecord -D plughw:CARD=CMTECK,DEV=0 -f S16_LE -r 16000 -d 3 test.wav
aplay test.wav

# Check volume
alsamixer

# Restart ALSA
sudo systemctl restart alsa-restore
```

### High Memory Usage

```bash
# Check current usage
free -h

# Kill process if needed
sudo systemctl stop hal-pipecat

# Clear cache
sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'

# Restart service
sudo systemctl start hal-pipecat
```

### API Rate Limits

```bash
# Check Anthropic usage
# Visit: https://console.anthropic.com/settings/usage

# Reduce conversation length in prompts.py
# Add rate limiting in hal_tools.py
```

### Face Recognition Not Working

```bash
# Check camera
libcamera-hello --list-cameras

# Check face database
cat /home/erik/hal9000/backend/known_faces.json

# Test face recognition
cd /home/erik/hal9000/backend
python face_recognition_service.py
```

---

## Security Considerations

### API Keys

```bash
# Never commit .env files
echo ".env" >> .gitignore

# Use environment variables in production
export ANTHROPIC_API_KEY=your_key

# Or use secrets manager (AWS Secrets Manager, etc.)
```

### Network Security

```bash
# Firewall rules
sudo ufw allow 5000/tcp  # Flask backend
sudo ufw enable

# SSL/TLS for production
# Use nginx reverse proxy with Let's Encrypt
```

### Camera Privacy

```bash
# Disable camera when not needed
# Set CAMERA_TYPE=opencv in .env
# Or physically disconnect camera
```

---

## Backup & Recovery

### Backup Memory Store

```bash
# Backup conversations
tar -czf hal_memory_backup_$(date +%Y%m%d).tar.gz /home/erik/hal9000/memory/

# Restore
tar -xzf hal_memory_backup_20260131.tar.gz -C /
```

### Backup Configuration

```bash
# Backup .env and known faces
cp /home/erik/hal9000/backend_pipecat/.env ~/backups/
cp /home/erik/hal9000/backend/known_faces.json ~/backups/
```

---

## Upgrade Process

```bash
# 1. Stop service
sudo systemctl stop hal-pipecat

# 2. Backup
tar -czf hal_backup_$(date +%Y%m%d).tar.gz /home/erik/hal9000/

# 3. Pull updates
cd /home/erik/hal9000
git pull

# 4. Update dependencies
cd backend_pipecat
pip install --upgrade -r requirements.txt

# 5. Restart service
sudo systemctl start hal-pipecat

# 6. Check status
sudo systemctl status hal-pipecat
```

---

## Performance Benchmarks

Expected performance on various platforms:

| Platform | Latency | CPU Usage | Memory |
|----------|---------|-----------|--------|
| Raspberry Pi 5 | 1-2s | 60-80% | 1.5GB |
| Raspberry Pi 4 | 2-3s | 80-100% | 1.8GB |
| AWS t3.medium | <1s | 30-50% | 1.2GB |
| Desktop (i7) | <0.5s | 10-20% | 1.0GB |

---

## Support

For deployment issues:

1. Check logs first
2. Review this guide
3. See main CLAUDE.md for architecture
4. Open issue on GitHub: https://github.com/eriksalo/hal9000/issues

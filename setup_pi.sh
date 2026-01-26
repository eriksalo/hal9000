#!/bin/bash
# HAL 9000 Raspberry Pi Setup Script
# For Raspberry Pi 5 with Pi AI HAT+ 2 and Pi Camera
# Run this on your Raspberry Pi 5 to automatically set up HAL 9000

set -e  # Exit on error

echo "========================================="
echo "HAL 9000 Raspberry Pi 5 Setup"
echo "With Pi AI HAT+ 2 and Pi Camera support"
echo "========================================="
echo ""

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Warning: This doesn't appear to be a Raspberry Pi"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Update system
echo "Step 1: Updating system..."
sudo apt update
sudo apt upgrade -y

# Install system dependencies
echo "Step 2: Installing system dependencies..."
sudo apt install -y \
    python3 python3-pip python3-venv \
    git curl build-essential nginx \
    cmake libopenblas-dev liblapack-dev \
    libjpeg-dev zlib1g-dev libpng-dev \
    portaudio19-dev \
    alsa-utils

# Install Pi Camera support
echo "Step 3: Installing Pi Camera support..."
sudo apt install -y \
    python3-libcamera \
    python3-picamera2 \
    libcamera-apps

# Install Hailo SDK for Pi AI HAT+ (if available)
echo "Step 4: Setting up Pi AI HAT+ support..."
if dpkg -l | grep -q hailo; then
    echo "Hailo packages already installed"
else
    # Check if AI HAT+ is detected
    if lspci | grep -qi hailo 2>/dev/null; then
        echo "Pi AI HAT+ detected, installing Hailo runtime..."
        # Hailo runtime for Raspberry Pi
        sudo apt install -y hailo-all 2>/dev/null || {
            echo "Note: Hailo packages not available in current repos."
            echo "Visit https://hailo.ai/developer-zone/ for latest drivers"
        }
    else
        echo "Pi AI HAT+ not detected - skipping Hailo installation"
        echo "If you have an AI HAT+, ensure it's properly connected"
    fi
fi

# Install Python packages
echo "Step 5: Installing Python packages..."

# Install system-provided packages that work better via apt
sudo apt install -y \
    python3-numpy \
    python3-opencv \
    python3-pil

# Install pip packages (using break-system-packages for Pi OS)
pip3 install --break-system-packages \
    flask flask-cors \
    anthropic python-dotenv pytz \
    duckduckgo-search \
    piper-tts

# Install face recognition dependencies
echo "Step 6: Installing face recognition..."
pip3 install --break-system-packages dlib face-recognition

# Install speech recognition dependencies
echo "Step 7: Installing speech recognition (Vosk)..."
pip3 install --break-system-packages vosk webrtcvad paho-mqtt

# Clone or update repository
if [ -d "/home/$USER/hal9000" ]; then
    echo "Step 8: HAL 9000 directory already exists. Pulling latest changes..."
    cd /home/$USER/hal9000
    git pull || true
else
    echo "Step 8: Cloning HAL 9000 repository..."
    cd /home/$USER
    git clone https://github.com/eriksalo/hal9000.git
    cd hal9000
fi

# Download HAL 9000 voice model
if [ ! -f "hal_9000_model/hal.onnx" ]; then
    echo "Step 9: Downloading HAL 9000 voice model..."
    cd hal_9000_model
    curl -L -o hal.onnx "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx"
    curl -L -o hal.onnx.json "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx.json"
    cd ..
else
    echo "Step 9: Voice model already exists, skipping download..."
fi

# Download Vosk speech recognition model
if [ ! -d "vosk_model/vosk-model-small-en-us-0.15" ]; then
    echo "Step 10: Downloading Vosk speech recognition model..."
    mkdir -p vosk_model
    cd vosk_model
    curl -L -o vosk-model-small-en-us-0.15.zip "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
    unzip -q vosk-model-small-en-us-0.15.zip
    rm vosk-model-small-en-us-0.15.zip
    cd ..
else
    echo "Step 10: Vosk model already exists, skipping download..."
fi

# Configure environment
echo "Step 11: Configuring environment..."
cd /home/$USER/hal9000
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    read -p "Enter your Anthropic API key: " api_key
    cat > .env <<EOF
ANTHROPIC_API_KEY=$api_key

# Camera settings (picamera2 for Pi Camera, opencv for USB webcam)
CAMERA_TYPE=picamera2
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_FPS=15

# Audio device settings
# Use 'default' for system default, or specific device like 'plughw:0,0'
# Run 'arecord -l' and 'aplay -l' to list available devices
AUDIO_INPUT_DEVICE=default
AUDIO_OUTPUT_DEVICE=default
MIC_GAIN=5
EOF
    echo ".env file created"
else
    echo ".env file already exists"
    # Check if new env vars exist, add if not
    if ! grep -q "CAMERA_TYPE" .env; then
        echo "" >> .env
        echo "# Camera settings (added by setup script)" >> .env
        echo "CAMERA_TYPE=picamera2" >> .env
        echo "CAMERA_WIDTH=1280" >> .env
        echo "CAMERA_HEIGHT=720" >> .env
        echo "Updated .env with camera settings"
    fi
    if ! grep -q "AUDIO_INPUT_DEVICE" .env; then
        echo "" >> .env
        echo "# Audio device settings (added by setup script)" >> .env
        echo "AUDIO_INPUT_DEVICE=default" >> .env
        echo "AUDIO_OUTPUT_DEVICE=default" >> .env
        echo "MIC_GAIN=5" >> .env
        echo "Updated .env with audio settings"
    fi
fi

# Create systemd service for backend
echo "Step 12: Creating systemd service for backend..."
sudo tee /etc/systemd/system/hal9000-backend.service > /dev/null <<EOF
[Unit]
Description=HAL 9000 Backend API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/hal9000/backend
Environment="PATH=/home/$USER/.local/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/home/$USER/hal9000/.env
ExecStart=/usr/bin/python3 app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Configure Nginx
echo "Step 13: Configuring Nginx..."
sudo tee /etc/nginx/sites-available/hal9000 > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    # Serve frontend
    location / {
        root /home/$USER/hal9000/frontend;
        try_files \$uri \$uri/ /index.html;
    }

    # Proxy API requests to Flask backend
    location /api/ {
        proxy_pass http://localhost:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }

    # Debug dashboard
    location /debug {
        proxy_pass http://localhost:8080;
        proxy_set_header Host \$host;
    }

    location /health {
        proxy_pass http://localhost:8080;
        proxy_set_header Host \$host;
    }
}
EOF

# Enable Nginx site
sudo ln -sf /etc/nginx/sites-available/hal9000 /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# Enable camera interface
echo "Step 14: Ensuring camera interface is enabled..."
if ! grep -q "^camera_auto_detect=1" /boot/firmware/config.txt 2>/dev/null; then
    echo "Note: Ensure camera is enabled in raspi-config or config.txt"
fi

# Enable and start services
echo "Step 15: Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable hal9000-backend.service
sudo systemctl restart hal9000-backend.service

# Wait for backend to start
echo "Waiting for backend to start..."
sleep 5

# Check status
echo ""
echo "========================================="
echo "Installation Complete!"
echo "========================================="
echo ""

# Get IP address
IP=$(hostname -I | awk '{print $1}')

echo "Backend status:"
sudo systemctl status hal9000-backend.service --no-pager -l | head -10
echo ""

echo "Nginx status:"
sudo systemctl status nginx --no-pager | head -5
echo ""

echo "Access HAL 9000 at:"
echo "  http://raspberrypi.local"
echo "  http://$IP"
echo ""
echo "Debug dashboard at:"
echo "  http://$IP/debug"
echo ""

echo "Hardware Detection:"
# Check camera
if v4l2-ctl --list-devices 2>/dev/null | grep -q ""; then
    echo "  Camera: $(v4l2-ctl --list-devices 2>/dev/null | head -1)"
else
    echo "  Camera: Not detected via v4l2"
fi

# Check audio devices
echo "  Audio Input: $(arecord -l 2>/dev/null | grep 'card' | head -1 || echo 'None detected')"
echo "  Audio Output: $(aplay -l 2>/dev/null | grep 'card' | head -1 || echo 'None detected')"

# Check for AI HAT+
if lspci 2>/dev/null | grep -qi hailo; then
    echo "  AI HAT+: Detected"
else
    echo "  AI HAT+: Not detected (optional)"
fi
echo ""

echo "To view logs:"
echo "  Backend: journalctl -u hal9000-backend.service -f"
echo ""

echo "To restart backend:"
echo "  sudo systemctl restart hal9000-backend.service"
echo ""

echo "To configure audio devices:"
echo "  List input devices:  arecord -l"
echo "  List output devices: aplay -l"
echo "  Edit .env and set AUDIO_INPUT_DEVICE and AUDIO_OUTPUT_DEVICE"
echo ""

echo "Setup complete! HAL 9000 is operational."

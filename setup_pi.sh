#!/bin/bash
# HAL 9000 Raspberry Pi Setup Script
# Run this on your Raspberry Pi 5 to automatically set up HAL 9000

set -e  # Exit on error

echo "========================================="
echo "HAL 9000 Raspberry Pi 5 Setup"
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

# Install dependencies
echo "Step 2: Installing dependencies..."
sudo apt install -y python3 python3-pip python3-venv git curl build-essential nginx

# Install Python packages
echo "Step 3: Installing Python packages..."
pip3 install --break-system-packages flask flask-cors anthropic python-dotenv pytz duckduckgo-search piper-tts

# Check if already in hal9000 directory
if [ -d "/home/$USER/hal9000" ]; then
    echo "HAL 9000 directory already exists. Pulling latest changes..."
    cd /home/$USER/hal9000
    git pull
else
    # Clone repository
    echo "Step 4: Cloning HAL 9000 repository..."
    cd /home/$USER
    git clone https://github.com/eriksalo/hal9000.git
    cd hal9000
fi

# Check for model file
if [ ! -f "hal_9000_model/hal.onnx" ]; then
    echo "Step 5: Downloading HAL 9000 voice model..."
    cd hal_9000_model
    curl -L -o hal.onnx "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx"
    curl -L -o hal.onnx.json "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx.json"
    cd ..
else
    echo "Step 5: Voice model already exists, skipping download..."
fi

# Configure environment
echo "Step 6: Configuring environment..."
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    read -p "Enter your Anthropic API key: " api_key
    echo "ANTHROPIC_API_KEY=$api_key" > .env
    echo ".env file created"
else
    echo ".env file already exists, skipping..."
fi

# Create systemd service for backend
echo "Step 7: Creating systemd service for backend..."
sudo tee /etc/systemd/system/hal9000-backend.service > /dev/null <<EOF
[Unit]
Description=HAL 9000 Backend API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/hal9000/backend
Environment="PATH=/home/$USER/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/bin/python3 app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Configure Nginx
echo "Step 8: Configuring Nginx..."
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
        proxy_pass http://localhost:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    location /health {
        proxy_pass http://localhost:5000;
        proxy_set_header Host \$host;
    }
}
EOF

# Enable Nginx site
sudo ln -sf /etc/nginx/sites-available/hal9000 /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# Enable and start services
echo "Step 9: Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable hal9000-backend.service
sudo systemctl start hal9000-backend.service

# Wait for backend to start
echo "Waiting for backend to start..."
sleep 3

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

echo "To view logs:"
echo "  Backend: journalctl -u hal9000-backend.service -f"
echo ""

echo "To restart backend:"
echo "  sudo systemctl restart hal9000-backend.service"
echo ""

echo "Setup complete! HAL 9000 is operational."

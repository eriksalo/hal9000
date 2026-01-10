# Raspberry Pi 5 Setup Guide

Complete guide to deploy HAL 9000 on your Raspberry Pi 5.

## Prerequisites

- Raspberry Pi 5 (4GB recommended)
- MicroSD card (64GB+) with Raspberry Pi OS installed
- Internet connection
- Power supply (5V/5A official adapter recommended)

## Step 1: Initial Pi Setup

### 1.1 Install Raspberry Pi OS

If not already done:
1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Flash **Raspberry Pi OS Lite (64-bit)** to your SD card
3. Enable SSH in advanced options
4. Set username/password
5. Configure WiFi
6. Boot the Pi

### 1.2 Connect via SSH

From your computer:
```bash
ssh your_username@raspberrypi.local
# Or use the IP address: ssh your_username@192.168.1.xxx
```

### 1.3 Update System

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

Wait for reboot, then reconnect via SSH.

## Step 2: Install Dependencies

### 2.1 Install Python and Build Tools

```bash
sudo apt install -y python3 python3-pip python3-venv git curl build-essential
```

### 2.2 Install Piper TTS

```bash
# Install Piper TTS
pip3 install piper-tts

# Verify installation
piper --version
```

### 2.3 Install Required Python Packages

```bash
pip3 install flask flask-cors anthropic python-dotenv pytz duckduckgo-search
```

## Step 3: Clone and Setup HAL 9000

### 3.1 Clone Repository

```bash
cd ~
git clone https://github.com/eriksalo/hal9000.git
cd hal9000
```

### 3.2 Download HAL 9000 Voice Model

The model should already be in the repo, but if not:
```bash
cd hal_9000_model
curl -L -o hal.onnx "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx"
curl -L -o hal.onnx.json "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx.json"
cd ..
```

### 3.3 Configure Environment

```bash
# Create .env file with your API key
nano .env
```

Add this line:
```
ANTHROPIC_API_KEY=your_api_key_here
```

Save (Ctrl+X, Y, Enter)

## Step 4: Test the Application

### 4.1 Start Backend

```bash
cd ~/hal9000/backend
python3 app.py
```

You should see:
```
Claude API initialized successfully
HAL 9000 TTS Server starting...
Model loaded from: /home/username/hal9000/hal_9000_model/hal.onnx
* Running on http://0.0.0.0:5000
```

### 4.2 Test from Another Computer

From your main computer's browser:
```
http://raspberrypi.local:5000
```

Or use the Pi's IP address:
```
http://192.168.1.xxx:5000
```

You should see... wait, we need to serve the frontend!

### 4.3 Serve Frontend (Option 1: Simple Python Server)

Open a new SSH terminal to the Pi:
```bash
cd ~/hal9000/frontend
python3 -m http.server 8080
```

Now access:
- Backend API: `http://raspberrypi.local:5000`
- Frontend: `http://raspberrypi.local:8080`

### 4.4 Test Voice and Chat

1. Open `http://raspberrypi.local:8080` in your browser
2. Click "Chat Mode"
3. Type a message or use voice input
4. HAL should respond with voice!

## Step 5: Run on Startup (Optional)

### 5.1 Create Systemd Service for Backend

```bash
sudo nano /etc/systemd/system/hal9000-backend.service
```

Add:
```ini
[Unit]
Description=HAL 9000 Backend API
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/hal9000/backend
Environment="PATH=/home/your_username/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/bin/python3 app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Replace `your_username` with your actual username.

Save and enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable hal9000-backend.service
sudo systemctl start hal9000-backend.service

# Check status
sudo systemctl status hal9000-backend.service
```

### 5.2 Create Systemd Service for Frontend

```bash
sudo nano /etc/systemd/system/hal9000-frontend.service
```

Add:
```ini
[Unit]
Description=HAL 9000 Frontend Server
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/hal9000/frontend
ExecStart=/usr/bin/python3 -m http.server 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable hal9000-frontend.service
sudo systemctl start hal9000-frontend.service

# Check status
sudo systemctl status hal9000-frontend.service
```

### 5.3 Verify Auto-Start

```bash
sudo reboot
```

After reboot, services should start automatically. Check:
```bash
sudo systemctl status hal9000-backend.service
sudo systemctl status hal9000-frontend.service
```

## Step 6: Better Deployment with Nginx (Recommended)

For a more professional setup:

### 6.1 Install Nginx

```bash
sudo apt install nginx -y
```

### 6.2 Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/hal9000
```

Add:
```nginx
server {
    listen 80;
    server_name raspberrypi.local;

    # Serve frontend
    location / {
        root /home/your_username/hal9000/frontend;
        try_files $uri $uri/ /index.html;
    }

    # Proxy API requests to Flask backend
    location /api/ {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /health {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/hal9000 /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Now you can access HAL at just:
```
http://raspberrypi.local
```

No port numbers needed!

## Troubleshooting

### Backend won't start
```bash
# Check logs
journalctl -u hal9000-backend.service -f

# Manual test
cd ~/hal9000/backend
python3 app.py
```

### Can't access from browser
```bash
# Check Pi's IP address
hostname -I

# Test backend locally on Pi
curl http://localhost:5000/health

# Check firewall (Pi OS usually has none by default)
sudo ufw status
```

### Piper TTS not found
```bash
# Check Piper installation
which piper
pip3 show piper-tts

# Reinstall if needed
pip3 install --upgrade piper-tts
```

### Model file missing
```bash
ls -lh ~/hal9000/hal_9000_model/
# Should show hal.onnx (61MB) and hal.onnx.json
```

## Performance Tips

### Reduce memory usage
Edit backend/app.py and reduce max_tokens for Claude API responses.

### Speed up TTS
Piper is already quite fast on Pi 5. If you need faster:
- Consider Piper's smaller voice models
- Or use cloud TTS (Google, AWS)

### Monitor resources
```bash
# Check CPU and memory
htop

# Check temperature
vcgencmd measure_temp
```

## Next Steps

Once basic deployment works:
1. Add camera for face recognition (future)
2. Add microphone for local voice input (future)
3. Add speaker for audio output (future)
4. Set up wake word detection (future)

## Finding Your Pi's IP Address

```bash
# On the Pi
hostname -I

# From your computer (scan network)
# Windows
arp -a

# Mac/Linux
arp -a | grep -i raspberry
# Or
sudo nmap -sn 192.168.1.0/24
```

## Quick Reference

**Start services:**
```bash
sudo systemctl start hal9000-backend
sudo systemctl start hal9000-frontend
```

**Stop services:**
```bash
sudo systemctl stop hal9000-backend
sudo systemctl stop hal9000-frontend
```

**View logs:**
```bash
journalctl -u hal9000-backend -f
journalctl -u hal9000-frontend -f
```

**Restart after code changes:**
```bash
cd ~/hal9000
git pull
sudo systemctl restart hal9000-backend
# Frontend serves static files, no restart needed
```

## Access URLs

- **With Nginx:** http://raspberrypi.local
- **Without Nginx:**
  - Frontend: http://raspberrypi.local:8080
  - Backend API: http://raspberrypi.local:5000
- **From your network:** http://[Pi-IP-address]

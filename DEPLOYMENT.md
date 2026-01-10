# AWS Amplify Deployment Guide

This guide walks you through deploying the HAL 9000 web application to AWS Amplify.

## Architecture Overview

The application consists of:
- **Frontend**: Static HTML/CSS/JavaScript (deployed on Amplify Hosting)
- **Backend**: Python Flask API (needs separate deployment)

## Deployment Options

### Option 1: Frontend Only on Amplify (Recommended for Testing)

Deploy just the frontend to Amplify and run the backend locally.

1. **Push to GitHub**
   ```bash
   git add .
   git commit -m "Initial commit"
   git push origin main
   ```

2. **Connect to Amplify**
   - Go to [AWS Amplify Console](https://console.aws.amazon.com/amplify/)
   - Click "New app" → "Host web app"
   - Connect your GitHub repository
   - Select the repository: `eriksalo/hal9000`
   - Select branch: `main`

3. **Configure Build Settings**
   - Amplify should auto-detect the `amplify.yml` file
   - The frontend will be served from the `frontend` directory

4. **Deploy**
   - Click "Save and deploy"
   - Wait for deployment to complete

5. **Update API URL**
   - After backend deployment (see Option 2), update `frontend/app.js`
   - Change `API_BASE_URL` to your backend URL
   - Commit and push changes

### Option 2: Full Stack Deployment

#### Step 1: Deploy Frontend to Amplify (as above)

#### Step 2: Deploy Backend to AWS

**Option A: AWS Lambda + API Gateway**

1. **Install AWS SAM CLI**
   ```bash
   pip install aws-sam-cli
   ```

2. **Create SAM Template** (`backend/template.yaml`)
   ```yaml
   AWSTemplateFormatVersion: '2010-09-09'
   Transform: AWS::Serverless-2016-10-31

   Resources:
     HAL9000Function:
       Type: AWS::Serverless::Function
       Properties:
         CodeUri: .
         Handler: app.lambda_handler
         Runtime: python3.13
         Timeout: 30
         MemorySize: 512
         Events:
           Api:
             Type: Api
             Properties:
               Path: /{proxy+}
               Method: ANY
   ```

3. **Modify Flask App for Lambda**
   Add to `backend/app.py`:
   ```python
   from flask import Flask
   from werkzeug.middleware.proxy_fix import ProxyFix

   # ... existing code ...

   # Add Lambda handler
   def lambda_handler(event, context):
       from werkzeug.wrappers import Request, Response
       from io import BytesIO

       # Handle API Gateway event
       # (Implementation depends on your needs)
       pass
   ```

4. **Deploy with SAM**
   ```bash
   cd backend
   sam build
   sam deploy --guided
   ```

**Option B: AWS App Runner (Simpler)**

1. **Create Dockerfile** (`backend/Dockerfile`)
   ```dockerfile
   FROM python:3.13-slim

   WORKDIR /app

   # Install dependencies
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt

   # Copy application
   COPY app.py .

   # Copy model files
   COPY ../hal_9000_model /app/hal_9000_model

   # Create output directory
   RUN mkdir -p /app/hal_9000_outputs

   EXPOSE 5000

   CMD ["python", "app.py"]
   ```

2. **Build and Push to ECR**
   ```bash
   aws ecr create-repository --repository-name hal9000-backend
   docker build -t hal9000-backend .
   docker tag hal9000-backend:latest <your-ecr-url>/hal9000-backend:latest
   docker push <your-ecr-url>/hal9000-backend:latest
   ```

3. **Create App Runner Service**
   - Go to AWS App Runner console
   - Create service from container registry
   - Select your ECR image
   - Configure port: 5000
   - Deploy

**Option C: EC2 Instance (Most Control)**

1. **Launch EC2 Instance**
   - Ubuntu 22.04 LTS
   - t3.medium or larger
   - Open ports: 80, 443, 22

2. **Install Dependencies**
   ```bash
   sudo apt update
   sudo apt install python3-pip nginx
   pip3 install -r requirements.txt
   ```

3. **Configure Nginx**
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://localhost:5000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

4. **Set Up Systemd Service**
   Create `/etc/systemd/system/hal9000.service`:
   ```ini
   [Unit]
   Description=HAL 9000 TTS Service
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/hal9000/backend
   ExecStart=/usr/bin/python3 app.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

5. **Start Service**
   ```bash
   sudo systemctl enable hal9000
   sudo systemctl start hal9000
   ```

### Step 3: Update Frontend API URL

1. **Get Backend URL**
   - From API Gateway, App Runner, or EC2

2. **Update Frontend**
   In `frontend/app.js`, change:
   ```javascript
   const API_BASE_URL = 'https://your-backend-url.com';
   ```

3. **Deploy Updated Frontend**
   ```bash
   git add frontend/app.js
   git commit -m "Update API URL"
   git push origin main
   ```

   Amplify will automatically redeploy.

## Environment Configuration

### Production Settings

1. **Backend Environment Variables**
   ```bash
   export FLASK_ENV=production
   export MODEL_PATH=/path/to/hal_9000_model
   export OUTPUT_DIR=/path/to/hal_9000_outputs
   ```

2. **Security**
   - Enable HTTPS
   - Configure CORS properly
   - Add rate limiting
   - Set up API authentication if needed

### CORS Configuration

In production, update `backend/app.py`:
```python
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://your-amplify-url.amplifyapp.com"]
    }
})
```

## Cost Estimates

### AWS Amplify (Frontend)
- Free tier: 1000 build minutes/month
- Hosting: ~$0.15 per GB served
- Estimated: $0-5/month for low traffic

### Backend Options
- **Lambda**: ~$0-10/month (low traffic)
- **App Runner**: ~$25/month (minimum)
- **EC2 t3.medium**: ~$30/month

## Monitoring

1. **CloudWatch Logs**
   - Enable for Lambda/App Runner/EC2

2. **Amplify Monitoring**
   - Check deployment logs
   - Monitor traffic

3. **Custom Metrics**
   - API response times
   - Error rates
   - TTS generation times

## Troubleshooting

### Frontend not loading
- Check Amplify build logs
- Verify amplify.yml configuration

### Backend errors
- Check CloudWatch logs
- Verify model files are included
- Check memory limits

### CORS issues
- Update CORS configuration in Flask app
- Verify allowed origins

## Cleanup

To avoid charges:
1. Delete Amplify app
2. Delete Lambda functions/App Runner service/EC2 instance
3. Delete ECR repositories
4. Delete CloudWatch logs

## Next Steps

1. Set up custom domain
2. Add SSL certificate
3. Configure CDN (CloudFront)
4. Add authentication
5. Set up monitoring and alerts

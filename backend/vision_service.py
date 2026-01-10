import cv2
import base64
import threading
import time
from PIL import Image
import io

class VisionService:
    def __init__(self):
        self.camera = None
        self.latest_frame = None
        self.running = False
        self.thread = None
        self.camera_index = 0  # Logitech C910 on /dev/video0

    def start(self):
        """Start the camera capture thread"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print(f"Vision service started on camera {self.camera_index}")

    def stop(self):
        """Stop the camera capture"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.camera:
            self.camera.release()
        self.camera = None

    def _capture_loop(self):
        """Continuously capture frames from camera"""
        try:
            self.camera = cv2.VideoCapture(self.camera_index)
            if not self.camera.isOpened():
                print(f"Failed to open camera {self.camera_index}")
                return

            # Set camera properties for C910 (1080p capable)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.camera.set(cv2.CAP_PROP_FPS, 15)

            print("Camera opened successfully")

            while self.running:
                ret, frame = self.camera.read()
                if ret:
                    self.latest_frame = frame
                time.sleep(0.1)  # Capture at ~10 FPS

        except Exception as e:
            print(f"Camera capture error: {e}")
        finally:
            if self.camera:
                self.camera.release()

    def get_frame_base64(self, max_size=800):
        """Get current frame as base64 for Claude Vision API"""
        if self.latest_frame is None:
            return None

        try:
            # Resize frame to reduce API costs
            frame = self.latest_frame.copy()
            height, width = frame.shape[:2]

            if width > max_size:
                scale = max_size / width
                new_width = max_size
                new_height = int(height * scale)
                frame = cv2.resize(frame, (new_width, new_height))

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Convert to PIL Image
            pil_image = Image.fromarray(frame_rgb)

            # Encode as JPEG
            buffer = io.BytesIO()
            pil_image.save(buffer, format='JPEG', quality=85)
            buffer.seek(0)

            # Base64 encode
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            return image_base64

        except Exception as e:
            print(f"Frame encoding error: {e}")
            return None

    def get_jpeg_frame(self):
        """Get current frame as JPEG bytes for streaming"""
        if self.latest_frame is None:
            return None

        try:
            # Encode frame as JPEG
            ret, buffer = cv2.imencode('.jpg', self.latest_frame,
                                      [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                return buffer.tobytes()
        except Exception as e:
            print(f"JPEG encoding error: {e}")

        return None

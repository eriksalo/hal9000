import cv2
import base64
import threading
import time
import os
from PIL import Image
import io

# Try to import picamera2 for Pi Camera support
try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False
    print("picamera2 not available - falling back to OpenCV")


class VisionService:
    def __init__(self):
        self.camera = None
        self.latest_frame = None
        self.running = False
        self.thread = None
        self.initialized = False
        self.lock = threading.Lock()

        # Camera type: 'picamera2' for Pi Camera, 'opencv' for USB webcam
        self.camera_type = os.getenv('CAMERA_TYPE', 'picamera2' if PICAMERA2_AVAILABLE else 'opencv')
        self.camera_index = int(os.getenv('CAMERA_INDEX', '0'))

        # Camera resolution settings
        self.width = int(os.getenv('CAMERA_WIDTH', '1280'))
        self.height = int(os.getenv('CAMERA_HEIGHT', '720'))
        self.fps = int(os.getenv('CAMERA_FPS', '15'))

    def start(self):
        """Start the camera capture thread"""
        if self.running:
            return

        self.initialized = True
        print(f"Vision service ready (camera type: {self.camera_type}, will initialize on first use)")

    def stop(self):
        """Stop the camera capture"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

        with self.lock:
            if self.camera:
                if self.camera_type == 'picamera2' and PICAMERA2_AVAILABLE:
                    try:
                        self.camera.stop()
                        self.camera.close()
                    except:
                        pass
                else:
                    self.camera.release()
            self.camera = None

    def _ensure_started(self):
        """Lazily start the camera thread on first use"""
        if not self.running and self.initialized:
            self.running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()
            print(f"Vision service started with {self.camera_type} camera")

    def _capture_loop(self):
        """Continuously capture frames from camera"""
        try:
            if self.camera_type == 'picamera2' and PICAMERA2_AVAILABLE:
                self._capture_loop_picamera2()
            else:
                self._capture_loop_opencv()
        except Exception as e:
            print(f"Camera capture error: {e}")
            import traceback
            traceback.print_exc()

    def _capture_loop_picamera2(self):
        """Capture loop using Picamera2 for Pi Camera"""
        try:
            self.camera = Picamera2()

            # Configure camera for video capture
            # Use RGB888 format for direct OpenCV/numpy compatibility
            config = self.camera.create_preview_configuration(
                main={"format": "RGB888", "size": (self.width, self.height)},
                buffer_count=4
            )
            self.camera.configure(config)
            self.camera.start()

            print(f"Pi Camera opened successfully ({self.width}x{self.height})")

            while self.running:
                # capture_array returns RGB format directly
                frame = self.camera.capture_array("main")

                if frame is not None:
                    # Convert RGB to BGR for OpenCV compatibility (face_recognition expects BGR)
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    with self.lock:
                        self.latest_frame = frame_bgr

                time.sleep(1.0 / self.fps)  # Control frame rate

        except Exception as e:
            print(f"Picamera2 error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.camera:
                try:
                    self.camera.stop()
                    self.camera.close()
                except:
                    pass

    def _capture_loop_opencv(self):
        """Capture loop using OpenCV for USB webcam (fallback)"""
        try:
            self.camera = cv2.VideoCapture(self.camera_index)
            if not self.camera.isOpened():
                print(f"Failed to open camera {self.camera_index}")
                return

            # Set camera properties
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.camera.set(cv2.CAP_PROP_FPS, self.fps)

            print(f"USB Camera opened successfully ({self.width}x{self.height})")

            while self.running:
                ret, frame = self.camera.read()
                if ret:
                    with self.lock:
                        self.latest_frame = frame
                time.sleep(0.1)  # Capture at ~10 FPS

        except Exception as e:
            print(f"OpenCV camera error: {e}")
        finally:
            if self.camera:
                self.camera.release()

    def get_frame_base64(self, max_size=800):
        """Get current frame as base64 for Claude Vision API"""
        self._ensure_started()

        # Wait briefly for first frame
        if self.latest_frame is None:
            time.sleep(0.5)

        with self.lock:
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
        self._ensure_started()

        with self.lock:
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

    def get_sized_jpeg_frame(self, size=480):
        """Get current frame resized and as JPEG bytes (for ESP32 display)"""
        self._ensure_started()

        with self.lock:
            if self.latest_frame is None:
                return None

            try:
                frame = self.latest_frame.copy()
                height, width = frame.shape[:2]

                # Resize to square for round display
                if width != size or height != size:
                    # Center crop to square first
                    min_dim = min(width, height)
                    x_start = (width - min_dim) // 2
                    y_start = (height - min_dim) // 2
                    frame = frame[y_start:y_start+min_dim, x_start:x_start+min_dim]

                    # Then resize to target size
                    frame = cv2.resize(frame, (size, size))

                # Encode as JPEG
                ret, buffer = cv2.imencode('.jpg', frame,
                                          [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    return buffer.tobytes()
            except Exception as e:
                print(f"Sized JPEG encoding error: {e}")

            return None

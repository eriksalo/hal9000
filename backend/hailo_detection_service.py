#!/usr/bin/env python3
"""
Hailo Detection Service for HAL 9000

Uses the Hailo-10H AI accelerator for fast person/object detection via YOLOv8.
"""

import os
import sys
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
import threading

# Default model path
DEFAULT_MODEL_PATH = "/usr/share/hailo-models/yolov8m_h10.hef"

# COCO class labels (80 classes)
COCO_LABELS = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush"
]

# Try to import Hailo components
HAILO_AVAILABLE = False
try:
    from hailo_platform import HEF, VDevice, FormatType, HailoSchedulingAlgorithm
    from hailo_platform.pyhailort.pyhailort import FormatOrder
    HAILO_AVAILABLE = True
    print("Hailo detection components loaded successfully")
except ImportError as e:
    print(f"Hailo detection not available: {e}")


class HailoDetectionService:
    """Service for object detection using Hailo-accelerated YOLOv8"""

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH, score_threshold: float = 0.5):
        """
        Initialize the Hailo detection service.

        Args:
            model_path: Path to the YOLOv8 HEF model file
            score_threshold: Minimum confidence threshold for detections
        """
        self.model_path = model_path
        self.score_threshold = score_threshold
        self.initialized = False
        self.lock = threading.Lock()

        # Inference components
        self.vdevice = None
        self.infer_model = None
        self.configured_model = None
        self.config_ctx = None
        self.input_shape = None
        self.output_names = []
        self.output_shapes = {}

        if not HAILO_AVAILABLE:
            print("Hailo detection not available - service disabled")
            return

        if not os.path.exists(model_path):
            print(f"Hailo model not found at {model_path}")
            return

        try:
            self._initialize()
        except Exception as e:
            print(f"Failed to initialize Hailo detection: {e}")
            import traceback
            traceback.print_exc()

    def _initialize(self):
        """Initialize the Hailo inference engine"""
        print(f"Initializing Hailo detection with {self.model_path}...")

        # Create VDevice with shared group for multi-model support
        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
        params.group_id = "SHARED"
        self.vdevice = VDevice(params)

        # Load HEF model
        self.hef = HEF(self.model_path)

        # Create inference model
        self.infer_model = self.vdevice.create_infer_model(self.model_path)
        self.infer_model.set_batch_size(1)

        # Get input shape
        input_info = self.hef.get_input_vstream_infos()[0]
        self.input_shape = input_info.shape  # (height, width, channels)
        print(f"Model input shape: {self.input_shape}")

        # Get output info
        output_infos = self.hef.get_output_vstream_infos()
        for info in output_infos:
            self.output_names.append(info.name)
            self.output_shapes[info.name] = info.shape
            print(f"Output layer: {info.name} shape: {info.shape}")

        # Configure model
        self.config_ctx = self.infer_model.configure()
        self.configured_model = self.config_ctx.__enter__()

        self.initialized = True
        print(f"Hailo detection initialized successfully")

    def preprocess(self, frame: np.ndarray) -> Tuple[np.ndarray, dict]:
        """
        Preprocess frame for YOLOv8 inference.

        Args:
            frame: BGR image from camera (any size)

        Returns:
            Tuple of (preprocessed frame, preprocessing info for postprocess)
        """
        img_h, img_w = frame.shape[:2]
        model_h, model_w = self.input_shape[0], self.input_shape[1]

        # Letterbox resize - maintain aspect ratio with padding
        scale = min(model_w / img_w, model_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)

        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Create padded image
        padded = np.full((model_h, model_w, 3), 114, dtype=np.uint8)  # Gray padding
        pad_x = (model_w - new_w) // 2
        pad_y = (model_h - new_h) // 2
        padded[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized

        # Store preprocessing info for coordinate transformation
        preproc_info = {
            'orig_h': img_h,
            'orig_w': img_w,
            'scale': scale,
            'pad_x': pad_x,
            'pad_y': pad_y,
            'model_h': model_h,
            'model_w': model_w
        }

        return padded, preproc_info

    def postprocess(self, outputs: dict, preproc_info: dict) -> List[Dict[str, Any]]:
        """
        Postprocess YOLOv8 outputs to extract detections.

        Args:
            outputs: Raw model outputs (per-class detections)
            preproc_info: Preprocessing info for coordinate transformation

        Returns:
            List of detections with keys: class_id, class_name, confidence, bbox (x1,y1,x2,y2)
        """
        detections = []

        # YOLOv8 outputs are organized by class
        # Each output tensor contains detections for that class
        # Format: [num_detections, 5] where 5 = [y1, x1, y2, x2, score] normalized

        for class_id, output_name in enumerate(self.output_names):
            if class_id >= len(COCO_LABELS):
                continue

            output = outputs.get(output_name)
            if output is None:
                continue

            # Handle different output shapes
            if output.ndim == 1:
                continue  # Skip if no valid shape

            # Iterate through detections for this class
            for det in output:
                if len(det) < 5:
                    continue

                # YOLOv8 format: [y1, x1, y2, x2, score] normalized to 0-1
                y1_norm, x1_norm, y2_norm, x2_norm, score = det[:5]

                if score < self.score_threshold:
                    continue

                # Denormalize to model coordinates
                model_h = preproc_info['model_h']
                model_w = preproc_info['model_w']

                x1_model = x1_norm * model_w
                y1_model = y1_norm * model_h
                x2_model = x2_norm * model_w
                y2_model = y2_norm * model_h

                # Remove padding
                x1_pad = x1_model - preproc_info['pad_x']
                y1_pad = y1_model - preproc_info['pad_y']
                x2_pad = x2_model - preproc_info['pad_x']
                y2_pad = y2_model - preproc_info['pad_y']

                # Scale back to original image coordinates
                scale = preproc_info['scale']
                x1 = int(x1_pad / scale)
                y1 = int(y1_pad / scale)
                x2 = int(x2_pad / scale)
                y2 = int(y2_pad / scale)

                # Clip to image bounds
                x1 = max(0, min(x1, preproc_info['orig_w']))
                y1 = max(0, min(y1, preproc_info['orig_h']))
                x2 = max(0, min(x2, preproc_info['orig_w']))
                y2 = max(0, min(y2, preproc_info['orig_h']))

                detections.append({
                    'class_id': class_id,
                    'class_name': COCO_LABELS[class_id],
                    'confidence': float(score),
                    'bbox': (x1, y1, x2, y2)
                })

        # Sort by confidence
        detections.sort(key=lambda x: x['confidence'], reverse=True)

        return detections

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Run object detection on a frame.

        Args:
            frame: BGR image from camera

        Returns:
            List of detections with class_id, class_name, confidence, bbox
        """
        if not self.initialized:
            return []

        with self.lock:
            try:
                # Preprocess
                preprocessed, preproc_info = self.preprocess(frame)

                # Create output buffers
                output_buffers = {}
                for name in self.output_names:
                    shape = self.infer_model.output(name).shape
                    output_buffers[name] = np.empty(shape, dtype=np.float32)

                # Create bindings
                binding = self.configured_model.create_bindings(output_buffers=output_buffers)
                binding.input().set_buffer(preprocessed)

                # Run synchronous inference
                self.configured_model.run([binding], timeout=5000)

                # Extract outputs
                outputs = {}
                for name in self.output_names:
                    outputs[name] = binding.output(name).get_buffer()

                # Postprocess
                detections = self.postprocess(outputs, preproc_info)

                return detections

            except Exception as e:
                print(f"Hailo detection error: {e}")
                import traceback
                traceback.print_exc()
                return []

    def detect_persons(self, frame: np.ndarray) -> List[Tuple[Tuple[int, int, int, int], float]]:
        """
        Detect persons in a frame (convenience method).

        Args:
            frame: BGR image from camera

        Returns:
            List of (bbox, confidence) tuples where bbox is (x1, y1, x2, y2)
        """
        detections = self.detect(frame)
        persons = [
            (det['bbox'], det['confidence'])
            for det in detections
            if det['class_name'] == 'person'
        ]
        return persons

    def detect_objects(self, frame: np.ndarray, max_objects: int = 10) -> List[Dict[str, Any]]:
        """
        Detect all objects in a frame for "what do you see" queries.

        Args:
            frame: BGR image from camera
            max_objects: Maximum number of objects to return

        Returns:
            List of detections (limited to max_objects)
        """
        detections = self.detect(frame)
        return detections[:max_objects]

    def describe_scene(self, frame: np.ndarray) -> str:
        """
        Generate a text description of detected objects in the scene.

        Args:
            frame: BGR image from camera

        Returns:
            Human-readable description of the scene
        """
        detections = self.detect_objects(frame, max_objects=15)

        if not detections:
            return "I don't detect any recognizable objects in my field of view."

        # Count objects by class
        object_counts = {}
        for det in detections:
            name = det['class_name']
            if name not in object_counts:
                object_counts[name] = 0
            object_counts[name] += 1

        # Build description
        parts = []
        for name, count in sorted(object_counts.items(), key=lambda x: -x[1]):
            if count == 1:
                article = "a" if name[0] not in "aeiou" else "an"
                parts.append(f"{article} {name}")
            else:
                parts.append(f"{count} {name}s")

        if len(parts) == 1:
            return f"I detect {parts[0]}."
        elif len(parts) == 2:
            return f"I detect {parts[0]} and {parts[1]}."
        else:
            return f"I detect {', '.join(parts[:-1])}, and {parts[-1]}."

    def is_available(self) -> bool:
        """Check if the detection service is available"""
        return self.initialized

    def stop(self):
        """Stop the detection service and release resources"""
        if self.config_ctx:
            try:
                self.config_ctx.__exit__(None, None, None)
            except:
                pass
            self.config_ctx = None
            self.configured_model = None

        self.vdevice = None
        self.initialized = False


# Singleton instance
_hailo_detection_service = None


def get_hailo_detection_service() -> HailoDetectionService:
    """Get or create the singleton Hailo detection service"""
    global _hailo_detection_service
    if _hailo_detection_service is None:
        _hailo_detection_service = HailoDetectionService()
    return _hailo_detection_service


if __name__ == "__main__":
    # Test the service
    print("Testing Hailo Detection Service...")
    service = get_hailo_detection_service()

    if service.is_available():
        print("Service is available!")
        print(f"Input shape: {service.input_shape}")
        print(f"Output layers: {len(service.output_names)}")

        # Test with a dummy frame
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        detections = service.detect(test_frame)
        print(f"Detections on blank frame: {len(detections)}")
    else:
        print("Service is not available")

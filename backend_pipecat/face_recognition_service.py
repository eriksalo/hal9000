import face_recognition
import json
import numpy as np
from pathlib import Path
import threading

class FaceRecognitionService:
    def __init__(self, database_path='face_database.json'):
        self.database_path = Path(__file__).parent.parent / database_path
        self.known_faces = {}
        self.lock = threading.Lock()
        self.load_database()

    def load_database(self):
        """Load known faces from JSON database"""
        if self.database_path.exists():
            try:
                with open(self.database_path, 'r') as f:
                    data = json.load(f)
                    # Convert lists back to numpy arrays
                    self.known_faces = {
                        name: np.array(encoding)
                        for name, encoding in data.items()
                    }
                print(f"Loaded {len(self.known_faces)} known faces from database")
            except Exception as e:
                print(f"Error loading face database: {e}")
                self.known_faces = {}
        else:
            print("No face database found, starting fresh")
            self.known_faces = {}

    def save_database(self):
        """Save known faces to JSON database"""
        with self.lock:
            try:
                # Convert numpy arrays to lists for JSON serialization
                data = {
                    name: encoding.tolist()
                    for name, encoding in self.known_faces.items()
                }
                with open(self.database_path, 'w') as f:
                    json.dump(data, f)
                print(f"Saved {len(self.known_faces)} faces to database")
            except Exception as e:
                print(f"Error saving face database: {e}")

    def detect_faces(self, frame):
        """
        Detect faces in a frame and return their encodings and locations
        Returns: (face_encodings, face_locations)
        """
        try:
            # Convert BGR (OpenCV) to RGB (face_recognition)
            rgb_frame = frame[:, :, ::-1]

            # Find faces in the frame
            face_locations = face_recognition.face_locations(rgb_frame)
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

            return face_encodings, face_locations
        except Exception as e:
            print(f"Error detecting faces: {e}")
            return [], []

    def recognize_faces(self, frame):
        """
        Recognize faces in a frame
        Returns: list of (name, location) tuples
        """
        face_encodings, face_locations = self.detect_faces(frame)

        results = []

        for face_encoding, face_location in zip(face_encodings, face_locations):
            name = "Unknown"

            if len(self.known_faces) > 0:
                # Compare to known faces
                known_names = list(self.known_faces.keys())
                known_encodings = list(self.known_faces.values())

                matches = face_recognition.compare_faces(known_encodings, face_encoding, tolerance=0.6)
                face_distances = face_recognition.face_distance(known_encodings, face_encoding)

                if True in matches:
                    best_match_index = np.argmin(face_distances)
                    if matches[best_match_index]:
                        name = known_names[best_match_index]

            results.append((name, face_location))

        return results

    def has_unknown_face(self, frame):
        """
        Check if there are any unknown faces in the frame
        Returns: (has_unknown, face_encoding, face_location)
        """
        face_encodings, face_locations = self.detect_faces(frame)

        for face_encoding, face_location in zip(face_encodings, face_locations):
            if len(self.known_faces) == 0:
                # No known faces, so this is unknown
                return True, face_encoding, face_location

            # Compare to known faces
            known_encodings = list(self.known_faces.values())
            matches = face_recognition.compare_faces(known_encodings, face_encoding, tolerance=0.6)

            if not any(matches):
                # No matches found, this is an unknown face
                return True, face_encoding, face_location

        return False, None, None

    def register_face(self, face_encoding, name):
        """
        Register a new face with a name
        """
        with self.lock:
            self.known_faces[name] = face_encoding
            self.save_database()
            print(f"Registered new face: {name}")
            return True

    def get_face_count(self):
        """Return number of known faces"""
        return len(self.known_faces)

    def get_known_names(self):
        """Return list of known face names"""
        return list(self.known_faces.keys())

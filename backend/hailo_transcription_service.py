"""
Hailo Whisper Transcription Service for HAL 9000

Uses the Hailo-10H AI accelerator for speech-to-text via OpenAI Whisper models.
"""

import os
import sys
import numpy as np
import wave
import tempfile
from pathlib import Path

# Add hailo-apps to path
HAILO_APPS_PATH = Path("/home/erik/hailo-apps")
if HAILO_APPS_PATH.exists():
    sys.path.insert(0, str(HAILO_APPS_PATH))

# Try to import Hailo Whisper components
HAILO_AVAILABLE = False
try:
    from hailo_apps.python.standalone_apps.speech_recognition.app.hailo_whisper_pipeline import (
        HailoWhisperPipeline,
    )
    from hailo_apps.python.standalone_apps.speech_recognition.common.audio_utils import load_audio
    from hailo_apps.python.standalone_apps.speech_recognition.common.preprocessing import (
        preprocess,
        improve_input_audio,
    )
    from hailo_apps.python.standalone_apps.speech_recognition.common.postprocessing import (
        clean_transcription,
    )
    from hailo_apps.python.standalone_apps.speech_recognition.app.whisper_hef_registry import (
        HEF_REGISTRY,
    )
    HAILO_AVAILABLE = True
    print("Hailo Whisper components loaded successfully")
except ImportError as e:
    print(f"Hailo Whisper not available: {e}")
    print("Falling back to Vosk for transcription")


class HailoTranscriptionService:
    """Service for speech-to-text using Hailo-accelerated Whisper"""

    def __init__(self, variant="tiny.en", hw_arch="h10h"):
        """
        Initialize the Hailo Whisper transcription service.

        Args:
            variant: Whisper model variant ("tiny", "tiny.en", "base")
            hw_arch: Hardware architecture ("hailo8", "hailo8l", "hailo10h")
        """
        self.variant = variant
        self.hw_arch = hw_arch
        self.pipeline = None
        self.initialized = False

        if not HAILO_AVAILABLE:
            print("Hailo Whisper not available - service disabled")
            return

        try:
            encoder_path = self._get_hef_path("encoder")
            decoder_path = self._get_hef_path("decoder")

            if not os.path.exists(encoder_path) or not os.path.exists(decoder_path):
                print(f"Hailo Whisper models not found at expected paths")
                print(f"  Encoder: {encoder_path}")
                print(f"  Decoder: {decoder_path}")
                return

            print(f"Initializing Hailo Whisper ({variant} on {hw_arch})...")
            # Note: multi_process_service is only for Hailo15 devices
            # Hailo-10H supports multi-process natively without this parameter
            self.pipeline = HailoWhisperPipeline(
                encoder_path,
                decoder_path,
                variant,
                multi_process_service=False
            )
            self.chunk_length = self.pipeline.get_model_input_audio_length()
            self.initialized = True
            print(f"Hailo Whisper initialized (max audio: {self.chunk_length}s)")

        except Exception as e:
            print(f"Failed to initialize Hailo Whisper: {e}")
            import traceback
            traceback.print_exc()

    def _get_hef_path(self, component: str) -> str:
        """Get path to HEF model file"""
        try:
            return HEF_REGISTRY[self.variant][self.hw_arch][component]
        except KeyError:
            # Fallback path construction
            hefs_dir = HAILO_APPS_PATH / "hefs" / self.hw_arch / self.variant
            if component == "encoder":
                return str(hefs_dir / f"{self.variant.replace('.', '_')}-whisper-encoder-10s.hef")
            else:
                return str(hefs_dir / f"{self.variant.replace('.', '_')}-whisper-decoder-fixed-sequence.hef")

    def transcribe_audio_data(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribe audio data using Hailo Whisper.

        Args:
            audio_data: Audio samples as numpy array (int16 or float32)
            sample_rate: Sample rate of audio (should be 16000)

        Returns:
            Transcribed text string
        """
        if not self.initialized:
            return ""

        try:
            # Convert to float32 if needed
            if audio_data.dtype == np.int16:
                audio_float = audio_data.astype(np.float32) / 32768.0
            elif audio_data.dtype == np.float32:
                audio_float = audio_data
            else:
                audio_float = audio_data.astype(np.float32)

            # Apply audio improvement (VAD, noise reduction)
            audio_improved, start_time = improve_input_audio(audio_float, vad=True)

            if start_time is None:
                print("No speech detected in audio")
                return ""

            chunk_offset = max(0, start_time - 0.2)

            # Preprocess to mel spectrograms
            mel_spectrograms = preprocess(
                audio_improved,
                is_nhwc=True,
                chunk_length=self.chunk_length,
                chunk_offset=chunk_offset
            )

            # Run inference
            transcription = ""
            for mel in mel_spectrograms:
                self.pipeline.send_data(mel)
                result = self.pipeline.get_transcription()
                transcription += clean_transcription(result) + " "

            return transcription.strip()

        except Exception as e:
            print(f"Hailo transcription error: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def transcribe_file(self, audio_path: str, fast_mode: bool = False) -> str:
        """
        Transcribe audio from a WAV file.

        Args:
            audio_path: Path to WAV file (16kHz mono expected)
            fast_mode: If True, skip VAD and noise reduction for faster processing

        Returns:
            Transcribed text string
        """
        if not self.initialized:
            return ""

        try:
            # Load audio using Hailo's utility
            audio_data = load_audio(audio_path)
            print(f"[Hailo] Loaded audio: {len(audio_data)} samples, max={np.max(np.abs(audio_data)):.4f}", flush=True)

            # Normalize audio to target peak level for low-sensitivity microphones
            max_val = np.max(np.abs(audio_data))
            if max_val > 0.001:  # Only normalize if there's actual audio
                target_peak = 0.7  # Target peak level
                actual_gain = min(target_peak / max_val, 50.0)  # Cap at 50x to avoid noise amplification
                audio_data = audio_data * actual_gain
                print(f"[Hailo] Normalized: {actual_gain:.1f}x gain, max={np.max(np.abs(audio_data)):.4f}", flush=True)
            else:
                print(f"[Hailo] Audio too quiet (max={max_val:.6f}), skipping normalization", flush=True)

            if fast_mode:
                # Fast mode: Skip VAD and noise reduction, process entire audio
                print("[Hailo] Fast mode: Skipping VAD and noise reduction", flush=True)
                mel_spectrograms = preprocess(
                    audio_data,
                    is_nhwc=True,
                    chunk_length=self.chunk_length,
                    chunk_offset=0
                )
            else:
                # Standard mode: Apply VAD and noise reduction
                audio_improved, start_time = improve_input_audio(audio_data, vad=True)
                print(f"[Hailo] VAD result: start_time={start_time}", flush=True)

                if start_time is None:
                    print("[Hailo] No speech detected in audio file", flush=True)
                    return ""

                chunk_offset = max(0, start_time - 0.2)

                mel_spectrograms = preprocess(
                    audio_improved,
                    is_nhwc=True,
                    chunk_length=self.chunk_length,
                    chunk_offset=chunk_offset
                )

            print(f"[Hailo] Processing {len(mel_spectrograms)} mel spectrogram chunks", flush=True)

            transcription = ""
            for i, mel in enumerate(mel_spectrograms):
                self.pipeline.send_data(mel)
                result = self.pipeline.get_transcription()
                cleaned = clean_transcription(result)
                print(f"[Hailo] Chunk {i}: raw='{result}' cleaned='{cleaned}'", flush=True)
                transcription += cleaned + " "

            return transcription.strip()

        except Exception as e:
            print(f"Hailo transcription error: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def is_available(self) -> bool:
        """Check if the Hailo transcription service is available"""
        return self.initialized

    def stop(self):
        """Stop the transcription pipeline"""
        if self.pipeline:
            try:
                self.pipeline.stop()
            except:
                pass
            self.pipeline = None
            self.initialized = False


# Singleton instance
_hailo_service = None

def get_hailo_transcription_service() -> HailoTranscriptionService:
    """Get or create the singleton Hailo transcription service"""
    global _hailo_service
    if _hailo_service is None:
        _hailo_service = HailoTranscriptionService()
    return _hailo_service


if __name__ == "__main__":
    # Test the service
    print("Testing Hailo Transcription Service...")
    service = get_hailo_transcription_service()

    if service.is_available():
        print("Service is available!")
        print(f"Max audio length: {service.chunk_length}s")
    else:
        print("Service is not available")

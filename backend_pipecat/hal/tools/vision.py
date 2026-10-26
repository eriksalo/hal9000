"""Let HAL look through the camera: frame -> Claude vision -> short description."""

from __future__ import annotations

import anthropic
from loguru import logger

from hal.prompts import VISION_SYSTEM
from hal.vision.camera import Camera


class CameraAnalyzer:
    def __init__(self, client: anthropic.AsyncAnthropic, camera: Camera, *, model: str = "claude-haiku-5-5"):
        self._client = client
        self._camera = camera
        self._model = model

    async def describe(self, question: str | None = None) -> str:
        image = self._camera.jpeg_base64(max_width=800)
        if image is None:
            return "The camera is not returning any image right now."
        prompt = question.strip() if question else "Describe what you see."
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=300,
                system=VISION_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
        except anthropic.APIConnectionError as exc:
            logger.warning(f"Vision connection error: {exc}")
            return "My visual processing is offline at the moment."
        except anthropic.APIStatusError as exc:
            logger.warning(f"Vision API error {exc.status_code}: {exc.message}")
            return "My visual processing encountered an error."
        if response.stop_reason == "refusal":
            return "I would rather not describe that."
        return " ".join(b.text for b in response.content if b.type == "text").strip() or "I see nothing of note."

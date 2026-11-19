"""Windows built-in OCR (Windows.Media.Ocr via pywinrt). Local, no model download."""

from __future__ import annotations

import asyncio

import cv2
import numpy as np

from .candidates import Rect
from .text_chunks import OcrWord


class OcrUnavailable(RuntimeError):
    pass


class WindowsOcr:
    def __init__(self, language: str = ""):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        if language:
            lang = Language(language)
            if not OcrEngine.is_language_supported(lang):
                raise OcrUnavailable(
                    f"OCR language '{language}' is not installed. Add it in Windows Settings > "
                    "Time & language > Language & region (with 'Optical character recognition')."
                )
            engine = OcrEngine.try_create_from_language(lang)
        else:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrUnavailable("No OCR language pack is installed for your Windows display languages")
        self._engine = engine
        self.language = engine.recognizer_language.language_tag
        self.max_dimension = OcrEngine.max_image_dimension

    def recognize(self, bgra: np.ndarray, scale: float = 1.0) -> tuple[list[list[OcrWord]], float]:
        """OCR a BGRA image. Returns (lines of words in *scaled* image coords, scale used)."""
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter

        h, w = bgra.shape[:2]
        scale = min(scale, self.max_dimension / max(h, w))
        if abs(scale - 1.0) > 1e-3:
            bgra = cv2.resize(bgra, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        bgra = np.ascontiguousarray(bgra)
        bgra[:, :, 3] = 255  # opaque; masked/transparent regions must not confuse OCR
        h, w = bgra.shape[:2]

        writer = DataWriter()
        writer.write_bytes(bgra.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED
        )
        result = asyncio.run(self._recognize(bitmap))
        lines = []
        for line in result.lines:
            words = []
            for word in line.words:
                b = word.bounding_rect
                words.append(OcrWord(word.text, Rect(int(b.x), int(b.y), int(b.x + b.width), int(b.y + b.height))))
            lines.append(words)
        return lines, scale

    async def _recognize(self, bitmap):
        return await self._engine.recognize_async(bitmap)

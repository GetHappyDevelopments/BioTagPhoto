from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def _silence_opencv_logs() -> None:
    try:
        if hasattr(cv2, "utils") and hasattr(cv2.utils, "logging"):
            # OpenCV Python bindings expose this API in many builds.
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
            return
    except Exception:
        pass

    try:
        if hasattr(cv2, "setLogLevel"):
            # Fallback API used by some OpenCV builds.
            level = getattr(cv2, "LOG_LEVEL_ERROR", None)
            if level is not None:
                cv2.setLogLevel(level)
    except Exception:
        pass


def _load_with_pillow(path: str) -> Optional[np.ndarray]:
    try:
        from PIL import Image  # Pillow fallback for damaged/non-standard JPEGs
    except Exception:
        return None

    try:
        with Image.open(str(path)) as pil_img:
            rgb = pil_img.convert("RGB")
            arr = np.asarray(rgb, dtype=np.uint8)
        if arr.ndim != 3 or arr.shape[2] != 3:
            return None
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        return None


_silence_opencv_logs()


def load_bgr_image(path: str) -> Optional[np.ndarray]:
    file_path = str(path)
    suffix = Path(file_path).suffix.lower()

    # JPEGs are where the noisy libjpeg warnings usually appear, so use Pillow first.
    if suffix in {".jpg", ".jpeg"}:
        img = _load_with_pillow(file_path)
        if img is not None:
            return img

    img = cv2.imread(file_path)
    if img is not None:
        return img

    return _load_with_pillow(file_path)

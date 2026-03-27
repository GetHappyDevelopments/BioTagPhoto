from __future__ import annotations

from typing import Optional

import cv2
import numpy as np


def load_bgr_image(path: str) -> Optional[np.ndarray]:
    img = cv2.imread(str(path))
    if img is not None:
        return img

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


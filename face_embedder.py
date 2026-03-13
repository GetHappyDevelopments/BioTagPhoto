from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import cv2


@dataclass(frozen=True)
class FaceRect:
    x: int
    y: int
    w: int
    h: int


class FaceEmbedder:
    """
    Offline ArcFace embeddings via InsightFace (onnxruntime).
    Uses FaceAnalysis with a local model directory.

    Expected model dir structure:
      <models_dir>/buffalo_l/...
    or any InsightFace model pack you have locally.

    Default: models_dir = ./models
    """

    def __init__(
        self,
        models_dir: str | Path = "models",
        model_name: str = "buffalo_l",
        ctx_id: int = -1,          # -1 = CPU, 0 = first GPU (if onnxruntime-gpu)
        det_size: Tuple[int, int] = (640, 640),
    ) -> None:
        self.models_dir = Path(models_dir).resolve()
        self.model_name = model_name
        self.ctx_id = ctx_id
        self.det_size = det_size

        # Lazy import so the rest of the app can run without insightface installed
        try:
            from insightface.app import FaceAnalysis  # type: ignore
            import onnxruntime as ort  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "insightface is not installed or not importable.\n"
                "Install:\n"
                "  pip install insightface onnxruntime opencv-python numpy\n"
                "Or GPU:\n"
                "  pip install insightface onnxruntime-gpu opencv-python numpy\n"
                f"\nOriginal error: {e}"
            ) from e

        if not self.models_dir.exists():
            raise RuntimeError(
                f"models_dir not found: {self.models_dir}\n"
                "Create ./models and place InsightFace models there (offline)."
            )

        available = list(ort.get_available_providers())
        providers: List[str] = []
        # Use CUDA only when explicitly requested and available.
        if int(self.ctx_id) >= 0 and "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
            self.ctx_id = -1

        # InsightFace expects 'root' pointing to a directory containing model folders
        self.app = FaceAnalysis(
            name=self.model_name,
            root=str(self.models_dir),
            providers=providers,
        )
        self.app.prepare(ctx_id=self.ctx_id, det_size=self.det_size)

    def embed_from_face_rect(
        self,
        image_path: str | Path,
        rect: FaceRect,
    ) -> Optional[np.ndarray]:
        """
        Returns L2-normalized embedding (float32, shape (512,)) or None.
        Uses the known face rect from DB; no re-detection needed.
        """
        path = Path(image_path)
        img_bgr = cv2.imread(str(path))
        if img_bgr is None:
            return None

        x, y, w, h = rect.x, rect.y, rect.w, rect.h
        if w <= 0 or h <= 0:
            return None

        h_img, w_img = img_bgr.shape[:2]
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(w_img, x + w)
        y1 = min(h_img, y + h)
        if x1 <= x0 or y1 <= y0:
            return None

        crop = img_bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        # For embedding we want InsightFace's alignment pipeline.
        # We run detection on the crop and pick the largest face.
        crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        faces = self.app.get(crop_rgb)
        if not faces:
            return None

        # pick largest detected face in crop
        def area(f) -> float:
            b = f.bbox  # [x1,y1,x2,y2]
            return float(max(0.0, (b[2] - b[0]) * (b[3] - b[1])))

        faces.sort(key=area, reverse=True)
        emb = faces[0].embedding
        if emb is None:
            return None

        emb = np.asarray(emb, dtype=np.float32)
        n = float(np.linalg.norm(emb))
        if n > 0:
            emb = emb / n
        return emb

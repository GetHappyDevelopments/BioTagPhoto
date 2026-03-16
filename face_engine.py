from __future__ import annotations

from pathlib import Path
import sys

import cv2
import numpy as np
import onnxruntime as ort

from model_config import MODEL_PACK_NAME, ensure_saved_model_root


class FaceEngine:
    def __init__(self):
        try:
            from insightface.app import FaceAnalysis  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "InsightFace is not installed for the active Python environment."
            ) from exc

        available = list(ort.get_available_providers())
        if "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            ctx_id = 0
        else:
            providers = ["CPUExecutionProvider"]
            ctx_id = -1

        app_kwargs: dict[str, object] = {
            "name": MODEL_PACK_NAME,
            "providers": providers,
        }
        models_root = self._resolve_models_root()
        if models_root is None:
            raise RuntimeError(
                "InsightFace model pack 'buffalo_l' not configured.\n"
                "Open Settings > Models or select the model folder when prompted."
            )
        app_kwargs["root"] = str(models_root)

        self.app = FaceAnalysis(**app_kwargs)
        self.app.prepare(ctx_id=ctx_id)

    def _resolve_models_root(self) -> Path | None:
        preferred = ensure_saved_model_root()
        if preferred is not None:
            return preferred

        candidates = [
            Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)),
            Path(__file__).resolve().parent,
            Path.cwd(),
        ]
        for base in candidates:
            models_dir = base / "models"
            pack_dir = models_dir / MODEL_PACK_NAME
            if pack_dir.exists() and pack_dir.is_dir():
                return models_dir
        return None

    def detect_faces(self, image_path: str) -> list[dict[str, object]]:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Could not read image: {image_path}")

        faces = self.app.get(img)

        results: list[dict[str, object]] = []
        for f in faces:
            x1, y1, x2, y2 = f.bbox.astype(int).tolist()
            results.append(
                {
                    "bbox": (x1, y1, x2 - x1, y2 - y1),
                    "embedding": f.embedding.astype(np.float32),
                }
            )

        return results

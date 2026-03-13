from __future__ import annotations

from typing import Protocol

import numpy as np


class EmbeddingModel(Protocol):
    def embed_face(self, bgr_crop: "np.ndarray") -> list[float]:
        """
        Return a face embedding for one BGR face crop.
        Implementations should return a non-empty vector.
        """


class StubEmbeddingModel:
    """
    Default model adapter that fails fast with a clear message.
    Replace with a real adapter (InsightFace/FaceNet/etc.) in production.
    """

    def __init__(self, hint: str | None = None) -> None:
        base = (
            "No embedding model configured. "
            "Provide an EmbeddingModel implementation and pass it to the rebuild job."
        )
        self._message = f"{base} {hint}".strip() if hint else base

    def embed_face(self, bgr_crop: "np.ndarray") -> list[float]:
        _ = bgr_crop
        raise RuntimeError(self._message)

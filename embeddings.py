from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import cv2
import numpy as np

from image_loader import load_bgr_image
from db import (
    iter_faces_for_embedding,
    list_people_ids,
    recompute_person_prototype,
    upsert_face_embedding,
)

Rect = tuple[int, int, int, int]


class EmbeddingBackend(Protocol):
    def embed(self, gray_64x64: np.ndarray) -> list[float]:
        """Return a normalized embedding vector as list[float]."""


@dataclass(frozen=True)
class BaselineEmbeddingBackend:
    """
    Deterministic placeholder embedding backend.
    Input must be grayscale 64x64.
    """

    def embed(self, gray_64x64: np.ndarray) -> list[float]:
        arr = np.asarray(gray_64x64, dtype=np.float32).reshape(-1)
        n = float(np.linalg.norm(arr))
        if n > 0.0:
            arr = arr / n
        return [float(x) for x in arr]


_BACKEND: EmbeddingBackend = BaselineEmbeddingBackend()


def set_embedding_backend(backend: EmbeddingBackend) -> None:
    global _BACKEND
    _BACKEND = backend


def _crop_face_bgr(image_path: str, face_rect: Rect) -> np.ndarray:
    path = str(Path(image_path))
    img = load_bgr_image(path)
    if img is None:
        raise FileNotFoundError(f"Image not found or unreadable: {path}")

    x, y, w, h = [int(v) for v in face_rect]
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid face rect (w/h <= 0): {face_rect}")

    img_h, img_w = img.shape[:2]
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(img_w, x + w)
    y1 = min(img_h, y + h)

    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"Face rect out of bounds: {face_rect}, image={img_w}x{img_h}")

    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        raise ValueError("Face crop is empty")
    return crop


def compute_face_embedding(image_path: str, face_rect: tuple[int, int, int, int]) -> list[float]:
    """
    Deterministic baseline embedding:
    crop -> resize 64x64 -> grayscale -> flatten -> L2 normalize.
    """
    crop_bgr = _crop_face_bgr(image_path, face_rect)
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    gray_64 = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
    return _BACKEND.embed(gray_64)


def rebuild_all_face_embeddings(model: str = "default") -> None:
    rows = list(iter_faces_for_embedding())
    for face_id, path, x, y, w, h, _person_id in rows:
        try:
            emb = compute_face_embedding(path, (x, y, w, h))
            upsert_face_embedding(int(face_id), emb, model=str(model))
        except Exception:
            # Keep running even if single files/faces fail.
            continue


def rebuild_all_person_prototypes(model: str = "default") -> None:
    for pid in list_people_ids():
        try:
            recompute_person_prototype(int(pid), model=str(model))
        except Exception:
            continue


# Backward-compatible aliases for existing callers

def compute_embedding_for_face(image_path: str, rect: Rect) -> np.ndarray:
    return np.asarray(compute_face_embedding(image_path, rect), dtype=np.float32)


def build_missing_face_embeddings() -> None:
    rebuild_all_face_embeddings(model="default")


def rebuild_person_prototypes() -> int:
    pids = list_people_ids()
    rebuild_all_person_prototypes(model="default")
    return len(pids)

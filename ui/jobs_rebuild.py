from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np
from PySide6.QtCore import QObject

from db import (
    get_face_embedding,
    list_all_faces_with_rects,
    recompute_all_person_prototypes,
    upsert_face_embedding,
)
from embedding_model_adapter import EmbeddingModel, StubEmbeddingModel
from ui.workers import WorkerRunner, WorkerTaskContext


@dataclass
class RebuildEmbeddingsResult:
    total: int = 0
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False
    prototypes_recomputed: bool = False


@dataclass
class RebuildEmbeddingsHandle:
    runner: WorkerRunner
    result: RebuildEmbeddingsResult


def _safe_crop_face(bgr_image: np.ndarray, x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
    if w <= 0 or h <= 0:
        return None

    img_h, img_w = bgr_image.shape[:2]
    x0 = max(0, int(x))
    y0 = max(0, int(y))
    x1 = min(img_w, int(x + w))
    y1 = min(img_h, int(y + h))

    if x1 <= x0 or y1 <= y0:
        return None

    crop = bgr_image[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    return crop


def _preprocess_face_crop(bgr_crop: np.ndarray) -> np.ndarray:
    """
    Lightweight default preprocessing:
    - ensure contiguous array
    - optional resize floor to avoid tiny crops
    """
    crop = np.ascontiguousarray(bgr_crop)
    h, w = crop.shape[:2]
    if h < 32 or w < 32:
        crop = cv2.resize(crop, (64, 64), interpolation=cv2.INTER_LINEAR)
    return crop


def build_rebuild_face_embeddings_task(
    model: EmbeddingModel,
    model_id: str = "default",
    recompute_prototypes_after: bool = False,
    result: Optional[RebuildEmbeddingsResult] = None,
) -> Callable[[WorkerTaskContext], None]:
    def _task(ctx: WorkerTaskContext) -> None:
        res = result if result is not None else RebuildEmbeddingsResult()
        faces = list_all_faces_with_rects()
        total = len(faces)
        res.total = int(total)
        res.ok = 0
        res.failed = 0
        res.skipped = 0
        res.cancelled = False
        res.prototypes_recomputed = False

        ctx.report_status(f"Rebuild face embeddings: 0/{total}")
        if total <= 0:
            ctx.report_progress(0, 0)
            ctx.report_status("Rebuild face embeddings: nothing to do")
            return

        for idx, (face_id, photo_path, x, y, w, h) in enumerate(faces, start=1):
            if ctx.check_cancelled():
                res.cancelled = True
                ctx.report_status(
                    f"Rebuild cancelled at {idx - 1}/{total} (ok={res.ok}, skipped={res.skipped}, failed={res.failed})"
                )
                return

            try:
                existing = get_face_embedding(int(face_id), model=str(model_id))
                if existing is not None and len(existing) > 0:
                    res.skipped += 1
                    ctx.report_progress(idx, total)
                    continue

                image = cv2.imread(photo_path)
                if image is None:
                    res.failed += 1
                    ctx.report_progress(idx, total)
                    continue

                crop = _safe_crop_face(image, x, y, w, h)
                if crop is None:
                    res.failed += 1
                    ctx.report_progress(idx, total)
                    continue

                crop = _preprocess_face_crop(crop)
                try:
                    embedding = model.embed_face(crop)
                except RuntimeError:
                    raise
                if len(embedding) == 0:
                    res.failed += 1
                    ctx.report_progress(idx, total)
                    continue

                upsert_face_embedding(int(face_id), embedding, model=str(model_id))
                res.ok += 1
            except RuntimeError:
                raise
            except Exception:
                res.failed += 1

            if idx % 10 == 0 or idx == total:
                ctx.report_status(
                    f"Rebuild face embeddings: {idx}/{total} (ok={res.ok}, skipped={res.skipped}, failed={res.failed})"
                )
            ctx.report_progress(idx, total)

        if recompute_prototypes_after and not ctx.check_cancelled():
            ctx.report_status("Recompute person prototypes...")
            recompute_all_person_prototypes(model_id=str(model_id))
            res.prototypes_recomputed = True

        ctx.report_status(
            f"Rebuild done: ok={res.ok}, skipped={res.skipped}, failed={res.failed}, total={res.total}"
        )

    return _task


def create_rebuild_face_embeddings_runner(
    parent: Optional[QObject] = None,
    model: Optional[EmbeddingModel] = None,
    model_id: str = "default",
) -> RebuildEmbeddingsHandle:
    adapter: EmbeddingModel = model if model is not None else StubEmbeddingModel()
    result = RebuildEmbeddingsResult()
    task = build_rebuild_face_embeddings_task(
        model=adapter,
        model_id=str(model_id),
        recompute_prototypes_after=True,
        result=result,
    )
    return RebuildEmbeddingsHandle(
        runner=WorkerRunner(task=task, parent=parent),
        result=result,
    )

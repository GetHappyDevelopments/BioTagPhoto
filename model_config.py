from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QSettings

from app_info import APP_NAME, APP_ORGANIZATION

MODEL_PACK_NAME = "buffalo_l"
MODEL_PATH_KEY = "models/insightface_root"


def _settings() -> QSettings:
    return QSettings(APP_ORGANIZATION, APP_NAME)


def get_saved_model_root() -> Path | None:
    raw = _settings().value(MODEL_PATH_KEY, "", str)
    text = str(raw).strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def set_saved_model_root(path: str | Path | None) -> None:
    settings = _settings()
    if path is None:
        settings.remove(MODEL_PATH_KEY)
    else:
        settings.setValue(MODEL_PATH_KEY, str(Path(path).expanduser().resolve()))
    settings.sync()


def normalize_model_root_selection(path: str | Path) -> Path:
    selected = Path(path).expanduser().resolve()
    if selected.name.lower() == MODEL_PACK_NAME.lower():
        return selected.parent
    return selected


def get_model_pack_dir(root: str | Path) -> Path:
    return normalize_model_root_selection(root) / MODEL_PACK_NAME


def is_valid_model_root(path: str | Path) -> bool:
    pack_dir = get_model_pack_dir(path)
    return pack_dir.exists() and pack_dir.is_dir() and any(pack_dir.glob("*.onnx"))


def describe_model_root(path: str | Path) -> str:
    root = normalize_model_root_selection(path)
    pack_dir = get_model_pack_dir(root)
    if not pack_dir.exists():
        return f"Missing model pack folder: {pack_dir}"
    if not any(pack_dir.glob("*.onnx")):
        return f"No ONNX model files found in: {pack_dir}"
    return f"Using model pack: {pack_dir}"


def candidate_model_roots() -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in _iter_candidate_roots():
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def find_available_model_root() -> Path | None:
    for root in candidate_model_roots():
        if is_valid_model_root(root):
            return root
    return None


def ensure_saved_model_root() -> Path | None:
    saved = get_saved_model_root()
    if saved is not None and is_valid_model_root(saved):
        return saved
    found = find_available_model_root()
    if found is not None:
        set_saved_model_root(found)
        return found
    return None


def _iter_candidate_roots() -> Iterable[Path]:
    saved = get_saved_model_root()
    if saved is not None:
        yield normalize_model_root_selection(saved)
    yield Path.home() / ".insightface" / "models"
    yield Path.cwd() / "models"

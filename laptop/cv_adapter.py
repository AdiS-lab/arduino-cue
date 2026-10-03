"""CV plug-in point. The teammate's detector goes here, and nothing else in the system knows about CV.

CONTRACT:
    detect(frames: list[np.ndarray]) -> {"label": str, "confidence": float}
    frames are BGR (OpenCV) images from one burst. Return {"label": "", "confidence": 0.0} if nothing found.

CV_MODE (env var):
    mock    (default) label from MOCK_LABELS (cycled) or from the mock camera's current sample filename
    module  import the teammate's function from CV_MODULE="package.module:function"
    http    POST the burst as JPEGs to CV_URL, expect the same JSON back
See docs/CV_INTEGRATION.md.
"""
import importlib
import itertools
import re
import sys

import config

EMPTY = {"label": "", "confidence": 0.0}

_mock_hint = ""
_mock_cycle = itertools.cycle(config.MOCK_LABELS) if config.MOCK_LABELS else None
_module_fn = None


def set_mock_hint(name: str):
    """The server passes the mock camera's current sample name (e.g. 'apple'). Used only in mock mode."""
    global _mock_hint
    _mock_hint = name or ""


def mode() -> str:
    return config.CV_MODE


def _normalize(r) -> dict:
    if not isinstance(r, dict):
        raise TypeError(f"detector must return a dict, got {type(r).__name__}")
    label = str(r.get("label") or "").strip()
    try:
        conf = float(r.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return {"label": label, "confidence": conf if label else 0.0}


def _detect_mock(frames):
    if not frames:
        return EMPTY
    if _mock_cycle is not None:
        return {"label": next(_mock_cycle), "confidence": 0.99}
    label = re.sub(r"[_\-]?\d+$", "", _mock_hint).replace("_", " ").strip()  # "cup_2" -> "cup"
    return {"label": label, "confidence": 0.9} if label else EMPTY


def _load_module_fn():
    global _module_fn
    if _module_fn is None:
        spec = config.CV_MODULE
        if ":" not in spec:
            raise ValueError('CV_MODULE must look like "package.module:function"')
        mod_name, fn_name = spec.split(":", 1)
        if str(config.ROOT) not in sys.path:  # allow modules at the repo root
            sys.path.insert(0, str(config.ROOT))
        _module_fn = getattr(importlib.import_module(mod_name), fn_name)
    return _module_fn


def _detect_http(frames):
    import cv2
    import requests
    files = []
    for i, f in enumerate(frames):
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            files.append(("frames", (f"frame_{i}.jpg", buf.tobytes(), "image/jpeg")))
    r = requests.post(config.CV_URL, files=files, timeout=config.CV_TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def detect(frames: list["np.ndarray"]) -> dict:
    """Input: list of BGR frames (burst). Output: {"label": str, "confidence": float} or {"label": "", "confidence": 0.0} if nothing found."""
    m = config.CV_MODE
    if m == "mock":
        return _normalize(_detect_mock(frames))
    if m == "module":
        return _normalize(_load_module_fn()(frames))
    if m == "http":
        return _normalize(_detect_http(frames))
    raise ValueError(f"unknown CV_MODE {m!r} (use mock, module or http)")

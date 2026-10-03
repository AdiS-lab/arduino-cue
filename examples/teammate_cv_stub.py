"""Example of what the CV teammate provides for CV_MODE=module.

    $env:CV_MODE="module"; $env:CV_MODULE="examples.teammate_cv_stub:detect"; python laptop\\server.py
"""
import numpy as np


def detect(frames: list[np.ndarray]) -> dict:
    # Replace with the real model. frames = burst of BGR images (H, W, 3) uint8.
    if not frames:
        return {"label": "", "confidence": 0.0}
    brightness = float(np.mean(frames[len(frames) // 2]))
    return {"label": "cup", "confidence": round(min(1.0, brightness / 255 + 0.5), 2)}

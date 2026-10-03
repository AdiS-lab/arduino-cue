# CV integration (for the CV teammate)

All object detection sits behind one function, `laptop/cv_adapter.py → detect(frames)`. You don't need to touch
the server, camera, UNO Q or UI.

## The contract
```python
def detect(frames: list["np.ndarray"]) -> dict:
    """Input: list of BGR frames (burst). Output: {"label": str, "confidence": float} or {"label": "", "confidence": 0.0} if nothing found."""
```
- `frames`: a burst of `BURST_N` (default 5) OpenCV **BGR** `uint8` images taken `BURST_GAP_MS` (default 100 ms) apart.
  They are already rotated, flipped and zoomed per the UI camera settings. The resolution is the camera's actual one: ESP32-CAM 640×480 by default (`framesize` in the UI), USB backup typically 1280×720.
- Return the single best label for the burst. You might vote across frames, or pick the sharpest frame.
- Return `{"label": "", "confidence": 0.0}` for "nothing found". The ring then vibrates 2 short pulses.
- **Time budget: ≤ ~3 s.** The server aborts the pipeline at 4.5 s (the ring gives up at 5 s). Burst capture takes ~0.5 s from a USB camera, ~1–1.5 s from the ESP32 over Wi-Fi.
- Labels are shown and spoken as-is. To change a word or add an emoji, edit `laptop/labels.py` (e.g. `"bottle" → "water 💧"`). This is optional.
- If your code raises, the server returns `status: "error"` and the ring vibrates one long pulse.

## The three modes (`CV_MODE` env var)
| Mode | What happens | Config |
|---|---|---|
| `mock` (default) | No model. Label comes from `MOCK_LABELS` (comma list, cycled) or from the mock camera's sample filename (`samples/apple.jpg` → `apple`). | `MOCK_LABELS="cup,ball"` (optional) |
| `module` | Imports your function in-process and calls it with the frames. | `CV_MODULE="package.module:function"` (path relative to the repo root) |
| `http` | POSTs the burst as JPEGs to your service and expects the same JSON back. Good if your model needs another Python env or GPU box. | `CV_URL="http://127.0.0.1:9000/detect"`, `CV_TIMEOUT_S=4` |

## Module mode: example stub
Put a file in the repo, e.g. `teammate_cv/detector.py`, plus an empty `teammate_cv/__init__.py`:
```python
import numpy as np

_model = None

def _load():
    global _model
    if _model is None:
        _model = ...  # load weights once, on first call
    return _model

def detect(frames: list[np.ndarray]) -> dict:
    if not frames:
        return {"label": "", "confidence": 0.0}
    model = _load()
    best = frames[len(frames) // 2]          # or score every frame and vote
    label, conf = "cup", 0.87                # <- your inference here
    return {"label": label, "confidence": float(conf)} if conf >= 0.4 else {"label": "", "confidence": 0.0}
```
Run it (PowerShell):
```powershell
$env:CV_MODE="module"; $env:CV_MODULE="teammate_cv.detector:detect"; python laptop\server.py
```
A working example is at `examples/teammate_cv_stub.py`: `$env:CV_MODULE="examples.teammate_cv_stub:detect"`.
Load the model at import time or on first call. The first trigger after start-up should not pay a 10 s load, so call your
`_load()` at import if it is slow.

## HTTP mode
Request: `POST CV_URL`, `multipart/form-data`, one or more files in field **`frames`** (JPEG, in burst order).
Response: `{"label": "cup", "confidence": 0.87}` (HTTP 200).

Test with the dummy service:
```powershell
python tools\dummy_cv_server.py --port 9000 --labels "cup,apple"
$env:CV_MODE="http"; $env:CV_URL="http://127.0.0.1:9000/detect"; python laptop\server.py
```
curl example (Windows 10/11 ships `curl.exe`):
```powershell
curl.exe -X POST http://127.0.0.1:9000/detect -F "frames=@samples/apple.jpg" -F "frames=@samples/cup.jpg"
# -> {"label":"cup","confidence":0.77}
```

## Test your detector without hardware
```powershell
$env:CAMERA_SOURCE="mock"; $env:CV_MODE="module"; $env:CV_MODULE="teammate_cv.detector:detect"
python laptop\server.py
# second terminal:
python laptop\keyboard_trigger.py --once
```
Put your own test photos in `samples/` (e.g. `samples/cup_1.jpg`). The mock camera cycles through them every 3 s.

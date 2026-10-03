"""All laptop-side configuration. Every value can be overridden with an env var.

PowerShell example:   $env:CAMERA_INDEX = "1"; python laptop\\server.py
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name, default, cast=str):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    if cast is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return cast(raw)


# ---- Server ---------------------------------------------------------------
HOST = _env("HOST", "0.0.0.0")          # 0.0.0.0 = reachable from UNO Q / phone on the hotspot
PORT = _env("PORT", 8000, int)

# ---- Camera ---------------------------------------------------------------
CAMERA_SOURCE = _env("CAMERA_SOURCE", "esp32")    # "esp32" (primary ring) | "usb" (backup: Inland/C270) | "mock"

# ESP32-CAM (primary). IP is printed on the ESP32 Serial Monitor at boot; can also be changed in the UI.
ESP32_IP = _env("ESP32_IP", "")
ESP32_HTTP_PORT = _env("ESP32_HTTP_PORT", 80, int)     # /capture /control /status /haptic /cue
ESP32_STREAM_PORT = _env("ESP32_STREAM_PORT", 81, int) # /stream
ESP32_TIMEOUT_S = _env("ESP32_TIMEOUT_S", 3.0, float)
BURST_MODE = _env("BURST_MODE", "snapshot")            # "snapshot" (repeated GET /capture) | "stream"
HAPTIC_FORWARD = _env("HAPTIC_FORWARD", True, bool)    # ble_remote/keyboard/ui triggers -> ESP32 /haptic

# USB camera (backup path)
CAMERA_INDEX = _env("CAMERA_INDEX", 0, int)       # 0-4; run laptop\find_camera.py to pick
CAMERA_BACKEND = _env("CAMERA_BACKEND", "DSHOW")  # "DSHOW" | "MSMF" | "ANY"
CAMERA_WIDTH = _env("CAMERA_WIDTH", 1280, int)    # falls back to 640x480 if refused
CAMERA_HEIGHT = _env("CAMERA_HEIGHT", 720, int)
CAMERA_MJPG = _env("CAMERA_MJPG", True, bool)
WARMUP_FRAMES = _env("WARMUP_FRAMES", 10, int)
BURST_N = _env("BURST_N", 5, int)
BURST_GAP_MS = _env("BURST_GAP_MS", 100, int)
MOCK_FPS = _env("MOCK_FPS", 15, int)
MOCK_SWITCH_S = _env("MOCK_SWITCH_S", 3.0, float)  # mock camera shows each sample this long

SAMPLES_DIR = ROOT / "samples"
CAPTURES_DIR = ROOT / "captures"
PROBE_DIR = ROOT / "probe"
CAMERA_SETTINGS_FILE = ROOT / "camera_settings.json"
UI_DIR = ROOT / "ui"

# ---- CV (teammate integration) -------------------------------------------
CV_MODE = _env("CV_MODE", "mock")                 # "mock" | "module" | "http"
CV_MODULE = _env("CV_MODULE", "")                 # e.g. "teammate_cv.detector:detect"
CV_URL = _env("CV_URL", "http://127.0.0.1:9000/detect")
CV_TIMEOUT_S = _env("CV_TIMEOUT_S", 4.0, float)
# mock mode: comma list; if empty the mock uses the current sample's filename
MOCK_LABELS = [s.strip() for s in _env("MOCK_LABELS", "").split(",") if s.strip()]

# ---- Output ---------------------------------------------------------------
TTS_ENABLED = _env("TTS_ENABLED", True, bool)
TTS_RATE = _env("TTS_RATE", 160, int)
NTFY_TOPIC = _env("NTFY_TOPIC", "")               # empty = messaging off (offline default)
NTFY_SERVER = _env("NTFY_SERVER", "https://ntfy.sh")

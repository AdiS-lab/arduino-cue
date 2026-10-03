"""Camera layer: USB (UVC) or mock source, a background grab thread, runtime settings, and burst capture.

The camera streams continuously into memory and nothing is written to disk.
Only burst() saves frames, to captures/<capture_id>_<i>.jpg.
"""
import json
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import config

BACKENDS = {"DSHOW": cv2.CAP_DSHOW, "MSMF": cv2.CAP_MSMF, "ANY": cv2.CAP_ANY}

DEFAULT_SETTINGS = {
    "camera_index": config.CAMERA_INDEX,
    "backend": config.CAMERA_BACKEND,
    "width": config.CAMERA_WIDTH,
    "height": config.CAMERA_HEIGHT,
    "mjpg": config.CAMERA_MJPG,
    "rotate": 0,            # 0 | 90 | 180 | 270
    "flip": "none",         # none | h | v
    "zoom": 1.0,            # 1.0 - 3.0, centered digital crop
    "brightness": None,     # None = leave camera default
    "exposure_auto": True,
    "exposure": -6.0,       # used when exposure_auto is False (Windows DSHOW: log2 seconds, e.g. -6)
    "sharpness": None,
    "warmup_frames": config.WARMUP_FRAMES,
    "burst_n": config.BURST_N,
    "burst_gap_ms": config.BURST_GAP_MS,
}
REOPEN_KEYS = {"camera_index", "backend", "width", "height", "mjpg"}
PROP_KEYS = {"brightness", "exposure_auto", "exposure", "sharpness"}


def load_settings(path: Path = config.CAMERA_SETTINGS_FILE) -> dict:
    s = dict(DEFAULT_SETTINGS)
    if path.exists():
        try:
            s.update({k: v for k, v in json.loads(path.read_text()).items() if k in DEFAULT_SETTINGS})
        except Exception as e:
            print(f"[camera] ignoring bad {path.name}: {e}")
    return s


def validate(updates: dict) -> dict:
    """Coerce and clamp incoming settings. Unknown keys raise ValueError."""
    out = {}
    for k, v in updates.items():
        if k not in DEFAULT_SETTINGS:
            raise ValueError(f"unknown setting: {k}")
        if k == "camera_index":
            v = int(v)
            if not 0 <= v <= 4:
                raise ValueError("camera_index must be 0-4")
        elif k == "backend":
            v = str(v).upper()
            if v not in BACKENDS:
                raise ValueError("backend must be DSHOW, MSMF or ANY")
        elif k in ("width", "height", "warmup_frames", "burst_n", "burst_gap_ms"):
            v = max(0, int(v))
            if k == "burst_n":
                v = max(1, min(v, 30))
        elif k in ("mjpg", "exposure_auto"):
            v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
        elif k == "rotate":
            v = int(v)
            if v not in (0, 90, 180, 270):
                raise ValueError("rotate must be 0/90/180/270")
        elif k == "flip":
            if v not in ("none", "h", "v"):
                raise ValueError("flip must be none/h/v")
        elif k == "zoom":
            v = min(3.0, max(1.0, float(v)))
        elif k in ("brightness", "sharpness", "exposure"):
            v = None if v in (None, "", "null") else float(v)
        out[k] = v
    return out


def process(frame: np.ndarray, s: dict) -> np.ndarray:
    """Digital zoom (centered crop), then rotate, then flip."""
    z = float(s.get("zoom", 1.0))
    if z > 1.0:
        h, w = frame.shape[:2]
        ch, cw = int(h / z), int(w / z)
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        frame = cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (w, h), interpolation=cv2.INTER_LINEAR)
    rot = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(s.get("rotate", 0))
    if rot is not None:
        frame = cv2.rotate(frame, rot)
    if s.get("flip") == "h":
        frame = cv2.flip(frame, 1)
    elif s.get("flip") == "v":
        frame = cv2.flip(frame, 0)
    return frame


# --------------------------------------------------------------------------
class MockSource:
    """Cycles images from samples/ so everything works without a camera."""

    def __init__(self, samples_dir: Path = config.SAMPLES_DIR):
        exts = (".jpg", ".jpeg", ".png", ".bmp")
        self.files = sorted(p for p in Path(samples_dir).glob("*") if p.suffix.lower() in exts)
        self.images = []
        for p in self.files:
            img = cv2.imread(str(p))
            if img is not None:
                self.images.append((p.stem, cv2.resize(img, (640, 480))))
        if not self.images:
            blank = np.full((480, 640, 3), 128, np.uint8)
            cv2.putText(blank, "no samples/", (180, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
            self.images = [("", blank)]
        self.t0 = time.time()
        self.current_name = self.images[0][0]

    def open(self, s):
        return True

    def read(self):
        time.sleep(1.0 / max(1, config.MOCK_FPS))
        i = int((time.time() - self.t0) / config.MOCK_SWITCH_S) % len(self.images)
        self.current_name, img = self.images[i]
        frame = img.copy()
        cv2.putText(frame, time.strftime("%H:%M:%S"), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        cv2.putText(frame, "MOCK", (10, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return True, frame

    def release(self):
        pass

    def info(self):
        return {"width": 640, "height": 480, "backend": "MOCK", "props": {}}


class USBSource:
    """A UVC webcam via OpenCV (DSHOW, falling back to MSMF)."""

    def __init__(self):
        self.cap = None
        self._info = {}

    def open(self, s):
        self.release()
        order = [s["backend"]] + [b for b in ("DSHOW", "MSMF") if b != s["backend"]]
        for name in order:
            cap = cv2.VideoCapture(int(s["camera_index"]), BACKENDS.get(name, cv2.CAP_ANY))
            if cap is not None and cap.isOpened():
                self.cap = cap
                self._info = {"backend": name}
                break
            if cap is not None:
                cap.release()
        if self.cap is None:
            self._info = {"backend": None, "error": f"could not open index {s['camera_index']}"}
            return False
        if s.get("mjpg"):
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        # Try the requested resolution, then fall back to 640x480.
        for w, h in ((s["width"], s["height"]), (640, 480)):
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            ok, f = self.cap.read()
            if ok and f is not None and f.shape[1] == w and f.shape[0] == h:
                break
        self._info["props"] = self.apply_props(s)
        for _ in range(int(s.get("warmup_frames", 10))):
            self.cap.read()
        self._info["width"] = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._info["height"] = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return True

    def apply_props(self, s):
        """Set camera properties and read them back. Many UVC cameras ignore some of them."""
        if self.cap is None:
            return {}
        report = {}

        def try_set(name, prop, value):
            ok = bool(self.cap.set(prop, value))
            rb = self.cap.get(prop)
            report[name] = {"requested": value, "set_ok": ok, "readback": rb,
                            "accepted": ok and rb is not None and abs(float(rb) - float(value)) < 1e-3}

        if s.get("brightness") is not None:
            try_set("brightness", cv2.CAP_PROP_BRIGHTNESS, s["brightness"])
        if s.get("sharpness") is not None:
            try_set("sharpness", cv2.CAP_PROP_SHARPNESS, s["sharpness"])
        # Auto-exposure values differ per backend (0.75/0.25 V4L-style, or 1/0). Try both.
        if s.get("exposure_auto", True):
            try_set("exposure_auto", cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
            if not report["exposure_auto"]["accepted"]:
                try_set("exposure_auto", cv2.CAP_PROP_AUTO_EXPOSURE, 1)
        else:
            try_set("exposure_auto", cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
            if not report["exposure_auto"]["accepted"]:
                try_set("exposure_auto", cv2.CAP_PROP_AUTO_EXPOSURE, 0)
            if s.get("exposure") is not None:
                try_set("exposure", cv2.CAP_PROP_EXPOSURE, s["exposure"])
        self._info["props"] = report
        return report

    def read(self):
        if self.cap is None:
            time.sleep(0.2)
            return False, None
        return self.cap.read()

    def release(self):
        if self.cap is not None:
            self.cap.release()
        self.cap = None

    def info(self):
        return dict(self._info)


# --------------------------------------------------------------------------
class Camera:
    def __init__(self, source: str = config.CAMERA_SOURCE, settings_file: Path = config.CAMERA_SETTINGS_FILE):
        self.source_kind = source
        self.settings_file = settings_file
        self.settings = load_settings(settings_file)
        self.src = MockSource() if source == "mock" else USBSource()
        self.lock = threading.Lock()
        self.frame = None          # latest processed frame
        self.frame_id = 0
        self.frame_ts = 0.0
        self.ok = False
        self.fail_streak = 0
        self.reconnects = 0
        self.last_error = ""
        self.mean_brightness = None
        self._reopen = threading.Event()
        self._stop = threading.Event()
        self.on_status = None      # optional callback(dict) for WebSocket status pushes
        self.thread = None

    # ---- lifecycle ----
    def start(self):
        self.ok = self.src.open(self.settings)
        if not self.ok:
            self.last_error = self.src.info().get("error", "open failed")
        self.thread = threading.Thread(target=self._loop, daemon=True, name="camera-grab")
        self.thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.src.release()

    def _loop(self):
        while not self._stop.is_set():
            if self._reopen.is_set():
                self._reopen.clear()
                self._do_reopen("settings changed")
            ok, raw = self.src.read()
            if not ok or raw is None:
                self.fail_streak += 1
                if self.fail_streak >= 3:
                    self._do_reopen("3 failed reads")
                    time.sleep(1.0)
                continue
            self.fail_streak = 0
            with self.lock:
                s = dict(self.settings)
            frame = process(raw, s)
            with self.lock:
                self.frame = frame
                self.frame_id += 1
                self.frame_ts = time.time()
                if not self.ok:
                    self.ok = True
                    self._notify()
            if self.frame_id % 30 == 0:
                self.mean_brightness = float(frame.mean())

    def _do_reopen(self, why):
        self.reconnects += 1
        was_ok = self.ok
        self.ok = self.src.open(self.settings)
        self.last_error = "" if self.ok else f"{why}: " + self.src.info().get("error", "reopen failed")
        print(f"[camera] reopen ({why}) -> {'OK' if self.ok else 'FAILED'}")
        if was_ok != self.ok or not self.ok:
            self._notify()

    def _notify(self):
        if self.on_status:
            try:
                self.on_status(self.status())
            except Exception:
                pass

    # ---- access ----
    def latest(self):
        with self.lock:
            return (None if self.frame is None else self.frame.copy()), self.frame_id

    def current_source_name(self) -> str:
        return getattr(self.src, "current_name", "")

    def status(self) -> dict:
        info = self.src.info()
        stale = self.frame_ts > 0 and time.time() - self.frame_ts > 2.0
        return {
            "camera": bool(self.ok and not stale),
            "source": self.source_kind,
            "index": self.settings["camera_index"],
            "backend": info.get("backend"),
            "actual_width": info.get("width"),
            "actual_height": info.get("height"),
            "props": info.get("props", {}),
            "reconnects": self.reconnects,
            "stale": stale,
            "black_frame": self.mean_brightness is not None and self.mean_brightness < 8,
            "mean_brightness": self.mean_brightness,
            "error": self.last_error,
        }

    # ---- settings ----
    def get_settings(self) -> dict:
        with self.lock:
            return dict(self.settings)

    def update_settings(self, updates: dict) -> dict:
        clean = validate(updates)
        with self.lock:
            self.settings.update(clean)
            s = dict(self.settings)
        try:
            self.settings_file.write_text(json.dumps(s, indent=2))
        except Exception as e:
            print(f"[camera] could not save settings: {e}")
        if REOPEN_KEYS & clean.keys():
            self._reopen.set()
        elif PROP_KEYS & clean.keys() and isinstance(self.src, USBSource):
            self.src.apply_props(s)
        return {"settings": s, "status": self.status()}

    # ---- burst ----
    def burst(self, capture_id: str, n=None, gap_ms=None, save=True, timeout_s=3.0):
        """Collect n distinct frames, gap_ms apart. Returns (frames, saved_paths)."""
        s = self.get_settings()
        n = int(n or s["burst_n"])
        gap = (gap_ms if gap_ms is not None else s["burst_gap_ms"]) / 1000.0
        frames, paths, last_id = [], [], -1
        deadline = time.time() + timeout_s
        while len(frames) < n and time.time() < deadline:
            f, fid = self.latest()
            if f is None or fid == last_id:
                time.sleep(0.01)
                continue
            last_id = fid
            frames.append(f)
            if len(frames) < n:
                time.sleep(gap)
        if save and frames:
            config.CAPTURES_DIR.mkdir(exist_ok=True)
            for i, f in enumerate(frames):
                p = config.CAPTURES_DIR / f"{capture_id}_{i}.jpg"
                cv2.imwrite(str(p), f)
                paths.append(p)
        return frames, paths


if __name__ == "__main__":
    # Quick check:  $env:CAMERA_SOURCE="mock"; python laptop\capture.py
    cam = Camera().start()
    time.sleep(1.5)
    print(json.dumps(cam.status(), indent=2, default=str))
    frames, paths = cam.burst(time.strftime("test_%H%M%S"))
    print(f"burst: {len(frames)} frames -> {[str(p) for p in paths]}")
    cam.stop()

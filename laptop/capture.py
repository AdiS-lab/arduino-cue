"""Camera layer: USB (UVC) or mock source, a background grab thread, runtime settings, and burst capture.

The camera streams continuously into memory and nothing is written to disk.
Only burst() saves frames, to captures/<capture_id>_<i>.jpg.
"""
import json
import os
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
    # ESP32-CAM: forwarded to http://<esp32_ip>/control?var=<k>&val=<v>. None = leave the camera's value.
    "esp32_ip": config.ESP32_IP,
    "burst_mode": config.BURST_MODE,  # snapshot | stream
    "framesize": None,      # OV2640: 5=QVGA 320x240, 8=VGA 640x480, 9=SVGA 800x600, 10=XGA, 13=UXGA
    "quality": None,        # JPEG 4-63, lower = better
    "contrast": None,       # -2..2 (brightness is shared with USB: -2..2 on ESP32)
    "hmirror": None,
    "vflip": None,
    "burst_n": config.BURST_N,
    "burst_gap_ms": config.BURST_GAP_MS,
}
REOPEN_KEYS = {"camera_index", "backend", "width", "height", "mjpg", "esp32_ip"}
ESP32_CONTROL_KEYS = ("framesize", "quality", "brightness", "contrast", "hmirror", "vflip")
PROP_KEYS = {"brightness", "exposure_auto", "exposure", "sharpness", *ESP32_CONTROL_KEYS}


ENV_OVERRIDES = {"esp32_ip": "ESP32_IP", "burst_mode": "BURST_MODE", "camera_index": "CAMERA_INDEX",
                 "backend": "CAMERA_BACKEND", "width": "CAMERA_WIDTH", "height": "CAMERA_HEIGHT"}


def load_settings(path: Path = config.CAMERA_SETTINGS_FILE) -> dict:
    s = dict(DEFAULT_SETTINGS)
    if path.exists():
        try:
            s.update({k: v for k, v in json.loads(path.read_text()).items() if k in DEFAULT_SETTINGS})
        except Exception as e:
            print(f"[camera] ignoring bad {path.name}: {e}")
    # An env var that is explicitly set beats the saved file (e.g. a new ESP32_IP after the hotspot reassigns IPs).
    for key, env in ENV_OVERRIDES.items():
        if os.environ.get(env):
            s[key] = DEFAULT_SETTINGS[key]
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
        elif k == "esp32_ip":
            v = str(v or "").strip().removeprefix("http://").rstrip("/")
        elif k == "burst_mode":
            if v not in ("snapshot", "stream"):
                raise ValueError("burst_mode must be snapshot or stream")
        elif k in ("framesize", "quality", "contrast"):
            v = None if v in (None, "", "null") else int(v)
            lim = {"framesize": (0, 13), "quality": (4, 63), "contrast": (-2, 2)}[k]
            if v is not None and not lim[0] <= v <= lim[1]:
                raise ValueError(f"{k} must be {lim[0]}..{lim[1]}")
        elif k in ("hmirror", "vflip"):
            v = None if v in (None, "", "null") else (v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes"))
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


class ESP32Source:
    """ESP32-CAM running esp32cam_firmware (CameraWebServer endpoints) over Wi-Fi.

    Preview/grab thread reads MJPEG from http://IP:81/stream. Bursts use GET http://IP/capture (snapshot mode).
    """

    def __init__(self):
        import requests
        self.requests = requests
        self.ip = ""
        self.resp = None
        self.buf = b""
        self.it = None
        self.current_name = ""   # mock server only: X-Sample header -> mock CV label
        self._info = {}

    def _url(self, path, stream=False):
        host = self.ip if ":" in self.ip else f"{self.ip}:{config.ESP32_STREAM_PORT if stream else config.ESP32_HTTP_PORT}"
        return f"http://{host}{path}"

    def open(self, s):
        self.release()
        self.ip = s.get("esp32_ip") or ""
        self._info = {"backend": f"ESP32 {self.ip or '(no ESP32_IP)'}", "props": {}}
        if not self.ip:
            self._info["error"] = "ESP32_IP not set (env var or UI camera settings)"
            time.sleep(1.0)
            return False
        try:
            st = self.requests.get(self._url("/status"), timeout=config.ESP32_TIMEOUT_S).json()
            self._info["esp32_status"] = {k: st.get(k) for k in ("framesize", "quality", "brightness", "contrast", "hmirror", "vflip")}
            self.apply_props(s)
            self.resp = self.requests.get(self._url("/stream", stream=True), stream=True,
                                          timeout=(config.ESP32_TIMEOUT_S, 5))
            self.resp.raise_for_status()
            self.it = self.resp.iter_content(chunk_size=8192)
            return True
        except Exception as e:
            self._info["error"] = f"ESP32 not reachable at {self.ip}: {type(e).__name__}"
            self.release()
            time.sleep(1.0)
            return False

    def apply_props(self, s):
        report = {}
        for k in ESP32_CONTROL_KEYS:
            v = s.get(k)
            if v is None:
                continue
            val = int(v) if not isinstance(v, bool) else int(v)
            try:
                ok = self.requests.get(self._url("/control"), params={"var": k, "val": val},
                                       timeout=config.ESP32_TIMEOUT_S).status_code == 200
            except Exception:
                ok = False
            report[k] = {"requested": val, "set_ok": ok, "readback": None, "accepted": False}
        if report:
            try:
                st = self.requests.get(self._url("/status"), timeout=config.ESP32_TIMEOUT_S).json()
                for k, r in report.items():
                    r["readback"] = st.get(k)
                    r["accepted"] = r["set_ok"] and st.get(k) == r["requested"]
            except Exception:
                pass
        self._info["props"] = report
        return report

    def read(self):
        if self.it is None:
            time.sleep(0.2)
            return False, None
        try:
            while True:
                a = self.buf.find(b"\xff\xd8")
                b = self.buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                if a >= 0 and b >= 0:
                    jpg, self.buf = self.buf[a:b + 2], self.buf[b + 2:]
                    frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue
                    self._info["width"], self._info["height"] = frame.shape[1], frame.shape[0]
                    return True, frame
                chunk = next(self.it)
                # mock server tags each part with X-Sample: <name>
                i = chunk.find(b"X-Sample: ")
                if i >= 0:
                    self.current_name = chunk[i + 10:chunk.find(b"\r\n", i)].decode(errors="ignore")
                self.buf += chunk
                if len(self.buf) > 4_000_000:
                    self.buf = b""
        except Exception:
            self.release()
            return False, None

    def snapshot(self):
        r = self.requests.get(self._url("/capture"), timeout=config.ESP32_TIMEOUT_S)
        r.raise_for_status()
        self.current_name = r.headers.get("X-Sample", self.current_name)
        return cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)

    def haptic(self, pattern: str) -> dict:
        r = self.requests.get(self._url("/haptic"), params={"pattern": pattern}, timeout=1.5)
        return {"ok": r.status_code == 200, "pattern": pattern}

    def cue_info(self) -> dict:
        return self.requests.get(self._url("/cue"), timeout=1.5).json()

    def release(self):
        if self.resp is not None:
            try:
                self.resp.close()
            except Exception:
                pass
        self.resp, self.it, self.buf = None, None, b""

    def info(self):
        return dict(self._info)


# --------------------------------------------------------------------------
class Camera:
    def __init__(self, source: str = config.CAMERA_SOURCE, settings_file: Path = config.CAMERA_SETTINGS_FILE):
        self.source_kind = source
        self.settings_file = settings_file
        self.settings = load_settings(settings_file)
        self.src = {"mock": MockSource, "esp32": ESP32Source}.get(source, USBSource)()
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
            "esp32_ip": self.settings.get("esp32_ip", ""),
            "burst_mode": self.settings.get("burst_mode"),
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
        elif PROP_KEYS & clean.keys() and hasattr(self.src, "apply_props") and self.ok:
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
        if isinstance(self.src, ESP32Source) and s.get("burst_mode", "snapshot") == "snapshot":
            while len(frames) < n and time.time() < deadline:
                try:
                    f = self.src.snapshot()
                    if f is not None:
                        frames.append(process(f, s))
                except Exception as e:
                    self.last_error = f"snapshot failed: {type(e).__name__}"
                    time.sleep(0.05)
                if len(frames) < n:
                    time.sleep(gap)
            n = 0  # skip the stream loop below
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

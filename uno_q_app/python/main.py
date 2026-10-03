# arduino-cue main UNO Q app (Linux side). UNTESTED ON HARDWARE.
#
# MCU sketch --Bridge.notify("button_pressed", n)--> on_button() --HTTP POST /trigger--> laptop
# laptop response --> beep(pattern) --Bridge.notify("play", pattern)--> MCU buzzer
#
# Uses only the Python standard library (urllib), so no requirements.txt is needed.
# This same file is imported by tools/mock_unoq.py on the laptop with a fake Bridge.

# ============================ EDIT THIS ============================
LAPTOP_IP = "192.168.137.1"   # laptop's IP on the phone hotspot (server.py prints it at startup)
PORT = 8000
# ===================================================================
HTTP_TIMEOUT_S = 5.0
HEALTH_RETRY_S = 5.0

import json
import threading
import time
import urllib.error
import urllib.request

try:
    from arduino.app_utils import App, Bridge   # confirmed import path (docs/UNO_Q_NOTES.md)
    ON_BOARD = True
except ImportError:                              # running on a laptop (tools/mock_unoq.py)
    App = Bridge = None
    ON_BOARD = False

# status -> MCU beep pattern (MCU sketch implements: ok, none, error, silent, boot_fail)
PATTERN = {"ok": "ok", "none": "none", "busy": "silent", "error": "error",
           "timeout": "error", "unreachable": "error"}

_in_flight = threading.Lock()


def base_url():
    return f"http://{LAPTOP_IP}:{PORT}"


def beep(pattern: str):
    """The ONE function that talks to the MCU buzzer. Edit here if the Bridge call differs on hardware."""
    Bridge.notify("play", pattern)


def http_json(method: str, path: str, body=None, timeout=HTTP_TIMEOUT_S) -> dict:
    """Returns parsed JSON, or {"status": "timeout"|"unreachable"|"error", "detail": ...}."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url() + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except (TimeoutError, OSError) as e:  # socket.timeout is a TimeoutError subclass on 3.10+
        reason = getattr(e, "reason", e)
        if isinstance(e, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(e):
            return {"status": "timeout", "detail": str(e)}
        if isinstance(e, urllib.error.HTTPError):
            return {"status": "error", "detail": f"HTTP {e.code}"}
        return {"status": "unreachable", "detail": str(e)}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def handle_trigger(source: str, n=0) -> str:
    """POST /trigger, beep the result, and return the pattern played."""
    resp = http_json("POST", "/trigger", {"source": source, "ts": int(time.time() * 1000)})
    status = resp.get("status", "error")
    pattern = PATTERN.get(status, "error")
    if status in ("unreachable", "timeout"):
        print(f"BUTTON OK, LAPTOP UNREACHABLE ({status}: {resp.get('detail', '')}) -> long beep")
    else:
        print(f"[{source} #{n}] -> {status} label={resp.get('label', '')!r} conf={resp.get('confidence', 0)}")
    beep(pattern)
    return pattern


def _run_once(source, n):
    if not _in_flight.acquire(blocking=False):
        print(f"[{source} #{n}] ignored: previous request still running")
        beep("silent")   # tell the MCU a reply arrived, so it does not play its own fallback beep
        return
    try:
        handle_trigger(source, n)
    finally:
        _in_flight.release()


def on_button(n=0):
    # Do the HTTP work off the Bridge callback thread (callback blocking behaviour is unconfirmed).
    threading.Thread(target=_run_once, args=("button", n), daemon=True).start()


def on_clap(value=0):
    threading.Thread(target=_run_once, args=("clap", value), daemon=True).start()


def health_check_loop(max_tries=None):
    """At boot: GET /health. On failure: 3 short beeps, retry every 5 s. On success: done."""
    tries = 0
    while max_tries is None or tries < max_tries:
        tries += 1
        r = http_json("GET", "/health", timeout=3)
        if r.get("ok"):
            print(f"laptop reachable at {base_url()}  camera={r.get('camera')} cv_mode={r.get('cv_mode')}")
            if tries > 1:
                beep("ok")
            return True
        print(f"laptop NOT reachable at {base_url()} ({r.get('status')}: {r.get('detail', '')}); retry in {HEALTH_RETRY_S:.0f}s")
        beep("boot_fail")
        time.sleep(HEALTH_RETRY_S)
    return False


if ON_BOARD:
    Bridge.provide("button_pressed", on_button)
    Bridge.provide("clap", on_clap)
    print(f"arduino-cue main app. LAPTOP = {base_url()}")
    threading.Thread(target=health_check_loop, daemon=True).start()
    App.run()

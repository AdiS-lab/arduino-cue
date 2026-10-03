"""Simulate the ESP32-CAM ring button (mirrors the logic in esp32cam_firmware.ino).

    python tools\\mock_ring.py                      # boot /health check, then Enter = button press
    python tools\\mock_ring.py --presses 3 --gap 2  # 3 presses then exit
    python tools\\mock_ring.py --ip 127.0.0.1 --port 8000

Prints the vibration pattern the real ring would play.
"""
import argparse
import time

import requests

PULSES = {"ok": "bzz (1 x 150 ms)", "none": "bz bz (2 x 100 ms)", "error": "BZZZZZZ (1 x 600 ms)",
          "boot": "bzz (boot pulse)", "boot_fail": "bz bz bz (3 pulses: laptop /health unreachable)",
          "silent": "(no vibration: busy)"}
STATUS_TO_PATTERN = {"ok": "ok", "none": "none", "busy": "silent", "error": "error",
                     "timeout": "error", "unreachable": "error"}


def vibrate(pattern):
    print(f"   [ring motor] {PULSES.get(pattern, pattern)}")
    return pattern


def health(base):
    try:
        return requests.get(base + "/health", timeout=3).json().get("ok", False)
    except Exception:
        return False


def press(base, n):
    """One button press -> POST /trigger -> vibration pattern (returned)."""
    print(f"BUTTON PRESSED #{n}")
    try:
        r = requests.post(base + "/trigger", json={"source": "ring", "device": "esp32cam", "ts": 0}, timeout=5)
        status = r.json().get("status", "error") if r.status_code == 200 else "error"
        if r.status_code == 200:
            j = r.json()
            print(f"[press #{n}] -> {status} label={j.get('label', '')!r}")
    except requests.Timeout:
        status = "timeout"
    except requests.RequestException:
        status = "unreachable"
    if status in ("timeout", "unreachable"):
        print(f"BUTTON OK, LAPTOP UNREACHABLE ({status}) -> long pulse")
    return vibrate(STATUS_TO_PATTERN.get(status, "error"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--presses", type=int, default=0)
    ap.add_argument("--gap", type=float, default=2.0, help="seconds between presses (firmware cooldown is 1.5 s)")
    a = ap.parse_args()
    base = f"http://{a.ip}:{a.port}"
    print(f"Mock ESP32-CAM ring -> {base}")
    vibrate("boot")
    if health(base):
        print("laptop reachable")
    else:
        print("laptop NOT reachable (firmware retries every 5 s)")
        vibrate("boot_fail")
    if a.presses:
        for n in range(1, a.presses + 1):
            press(base, n)
            time.sleep(a.gap)
        return
    print("Press Enter = ring button (Ctrl+C to quit)")
    n = 0
    while True:
        input()
        n += 1
        press(base, n)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

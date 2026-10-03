"""Bluetooth ring remote -> trigger. Pair a BT "camera shutter" / media ring with the laptop (Windows Bluetooth
settings). It shows up as a keyboard. This script listens for its key globally (even if the browser has focus).

    python laptop\\ble_remote.py                         # default keys: "volume up" or "enter"
    $env:BLE_KEYS="volume up,page down"; python laptop\\ble_remote.py
    python tools\\detect_key.py                          # find out which key name your ring sends

Each press -> POST /trigger {"source":"ble_remote","device":"laptop"}. The server then vibrates the ESP32 ring
(/haptic) with the result, if an ESP32 is configured.
Notes: uses the `keyboard` package (Windows: no admin needed; Linux: needs root).
"Enter" is global: pressing Enter anywhere on the laptop will also trigger. Remove it from BLE_KEYS if that is a problem.
"""
import os
import time

import requests

import config

KEYS = [k.strip().lower() for k in os.environ.get("BLE_KEYS", "volume up,enter").split(",") if k.strip()]
SUPPRESS = [k.strip().lower() for k in os.environ.get("BLE_SUPPRESS", "volume up").split(",") if k.strip()]
COOLDOWN_S = 1.5
URL = f"http://127.0.0.1:{config.PORT}/trigger"

_last = 0.0


def on_key(name: str, url: str = URL, now=None) -> dict | None:
    """Handle one key press. Returns the server response, or None if ignored (wrong key / cooldown)."""
    global _last
    name = (name or "").lower()
    now = time.time() if now is None else now
    if name not in KEYS:
        return None
    if now - _last < COOLDOWN_S:
        print(f"[ble] {name}: ignored (cooldown)")
        return None
    _last = now
    try:
        r = requests.post(url, json={"source": "ble_remote", "device": "laptop", "ts": int(now * 1000)}, timeout=6).json()
    except Exception as e:
        r = {"status": "error", "detail": str(e)}
    print(f"[ble] {name} -> {r.get('status')} {r.get('label', '')!r}")
    return r


def main():
    import keyboard  # imported here so on_key() is testable without the package / root
    print(f"BLE ring remote: listening for {KEYS} (suppressing {SUPPRESS}) -> {URL}   Ctrl+C to quit")
    for k in KEYS:
        keyboard.add_hotkey(k, lambda k=k: on_key(k), suppress=k in SUPPRESS)
    keyboard.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

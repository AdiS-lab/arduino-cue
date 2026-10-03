"""Trigger a capture from the keyboard (stand-in for the ring button).

    python laptop\\keyboard_trigger.py                 # Enter / Space = capture, q = quit
    python laptop\\keyboard_trigger.py --once          # one trigger, print result, exit
"""
import argparse
import sys
import time

import requests

import config


def fire(url):
    t0 = time.time()
    try:
        r = requests.post(url, json={"source": "keyboard", "ts": int(time.time() * 1000)}, timeout=6).json()
    except Exception as e:
        r = {"status": "error", "detail": str(e)}
    print(f"-> {r.get('status')}  label={r.get('label', '')!r}  conf={r.get('confidence', 0)}  "
          f"id={r.get('capture_id', '')}  ({(time.time() - t0) * 1000:.0f} ms)")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=f"http://127.0.0.1:{config.PORT}/trigger")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    if a.once:
        sys.exit(0 if fire(a.url).get("status") in ("ok", "none") else 1)
    print("Enter/Space = capture, q = quit")
    try:
        import msvcrt  # Windows: single keypress
        while True:
            ch = msvcrt.getwch()
            if ch.lower() == "q":
                break
            if ch in ("\r", " "):
                fire(a.url)
    except ImportError:
        while True:
            if input().strip().lower() == "q":
                break
            fire(a.url)


if __name__ == "__main__":
    main()

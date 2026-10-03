"""Scan camera indices 0-4 on DSHOW and MSMF. For each one, print whether it opens, the actual
resolution and the mean brightness (black frames are flagged), and save a snapshot to probe/.

    python laptop\\find_camera.py

Open the probe\\ folder and look at the snapshots to see which index is which lens, then set CAMERA_INDEX
(env var, or the UI camera panel).
"""
import sys
import time

import cv2

import config

BACKENDS = [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF)] if sys.platform == "win32" else [("ANY", cv2.CAP_ANY)]


def probe(index, name, api):
    cap = cv2.VideoCapture(index, api)
    if cap is None or not cap.isOpened():
        return {"open": False}
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    frame = None
    t0 = time.time()
    for _ in range(15):  # warm-up: many UVC cams return black for the first frames
        ok, f = cap.read()
        if ok and f is not None:
            frame = f
        if time.time() - t0 > 5:
            break
    cap.release()
    if frame is None:
        return {"open": True, "frame": False}
    config.PROBE_DIR.mkdir(exist_ok=True)
    path = config.PROBE_DIR / f"index{index}_{name}.jpg"
    cv2.imwrite(str(path), frame)
    mean = float(frame.mean())
    return {"open": True, "frame": True, "w": frame.shape[1], "h": frame.shape[0], "mean": mean,
            "black": mean < 8, "snapshot": str(path)}


def main():
    print(f"Scanning indices 0-4 on {[b[0] for b in BACKENDS]} ...\n")
    found = []
    for name, api in BACKENDS:
        for idx in range(5):
            try:
                r = probe(idx, name, api)
            except Exception as e:  # never crash the scan
                r = {"open": False, "error": str(e)}
            if not r.get("open"):
                print(f"  [{name}] index {idx}: closed")
            elif not r.get("frame"):
                print(f"  [{name}] index {idx}: OPEN but no frames (try other backend / replug)")
            else:
                flag = "  <-- BLACK FRAME (lens cap? wrong lens? needs light?)" if r["black"] else ""
                print(f"  [{name}] index {idx}: OPEN {r['w']}x{r['h']} mean={r['mean']:.0f}  -> {r['snapshot']}{flag}")
                found.append((name, idx))
    print()
    if found:
        print("Working cameras:", ", ".join(f"{n}:{i}" for n, i in found))
        print('Set e.g.:  $env:CAMERA_INDEX="1"; $env:CAMERA_BACKEND="DSHOW"   (or change it in the UI)')
    else:
        print("No camera produced frames. Check cable (data, not charge-only), Windows camera privacy settings,")
        print("close other apps using the camera, or try the Logitech C270 backup.")


if __name__ == "__main__":
    main()

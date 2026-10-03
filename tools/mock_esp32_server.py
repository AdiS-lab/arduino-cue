"""Pretend to be the ESP32-CAM ring firmware, so the ESP32 path works with no hardware.

Serves the same endpoints as esp32cam_firmware (CameraWebServer + arduino-cue additions):
    :HTTP_PORT     /capture  /status  /control?var=&val=  /haptic?pattern=  /cue
    :HTTP_PORT+1   /stream   (MJPEG)
Frames come from samples/. framesize/hmirror/vflip/brightness from /control are applied to the frames.
Every /haptic and /control call is recorded: GET /_calls returns them (used by tests).

    python tools\\mock_esp32_server.py                  # :8080 and :8081
    $env:CAMERA_SOURCE="esp32"; $env:ESP32_IP="127.0.0.1"; $env:ESP32_HTTP_PORT="8080"; $env:ESP32_STREAM_PORT="8081"
    python laptop\\server.py
"""
import argparse
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
FRAMESIZES = {5: (320, 240), 6: (400, 296), 7: (480, 320), 8: (640, 480), 9: (800, 600), 10: (1024, 768),
              11: (1280, 720), 12: (1280, 1024), 13: (1600, 1200)}

state = {"framesize": 8, "quality": 10, "brightness": 0, "contrast": 0, "saturation": 0, "hmirror": 0, "vflip": 0,
         "led_intensity": 0}
calls = {"haptic": [], "control": []}
presses = 0
images = [(p.stem, cv2.imread(str(p))) for p in sorted(SAMPLES.glob("*.jpg"))] or \
         [("", np.full((480, 640, 3), 100, np.uint8))]
t0 = time.time()
SWITCH_S = 3.0


def frame():
    name, img = images[int((time.time() - t0) / SWITCH_S) % len(images)]
    w, h = FRAMESIZES.get(state["framesize"], (640, 480))
    f = cv2.resize(img, (w, h))
    if state["hmirror"]:
        f = cv2.flip(f, 1)
    if state["vflip"]:
        f = cv2.flip(f, 0)
    if state["brightness"]:
        f = cv2.convertScaleAbs(f, alpha=1.0, beta=30 * state["brightness"])
    cv2.putText(f, "MOCK ESP32", (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, max(10, 100 - state["quality"])])
    return name, buf.tobytes()


api = FastAPI()      # port 80 equivalent
stream_api = FastAPI()  # port 81 equivalent


@api.get("/capture")
def capture():
    name, jpg = frame()
    return Response(jpg, media_type="image/jpeg", headers={"X-Sample": name})


@api.get("/status")
def status():
    return state


@api.get("/control")
def control(var: str, val: int):
    calls["control"].append({"var": var, "val": val, "t": time.time()})
    if var not in state:
        raise HTTPException(500, "unknown var")   # firmware also returns 500 for unknown vars
    state[var] = val
    return Response(status_code=200)


@api.get("/haptic")
def haptic(pattern: str = Query(...)):
    calls["haptic"].append({"pattern": pattern, "t": time.time()})
    print(f"[mock-esp32] haptic {pattern}")
    return {"ok": True, "pattern": pattern}


@api.get("/cue")
def cue():
    return {"device": "esp32cam", "presses": presses, "laptop_reachable": True, "laptop": "mock", "rssi": -50,
            "uptime_s": int(time.time() - t0)}


@api.get("/_calls")
def get_calls():
    return calls


@api.post("/_reset")
def reset():
    calls["haptic"].clear()
    calls["control"].clear()
    return {"ok": True}


def mjpeg():
    while True:
        name, jpg = frame()
        yield (b"--123456789000000000000987654321\r\nContent-Type: image/jpeg\r\nX-Sample: " + name.encode() +
               b"\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
        time.sleep(1 / 12)


@stream_api.get("/stream")
def stream():
    return StreamingResponse(mjpeg(), media_type="multipart/x-mixed-replace;boundary=123456789000000000000987654321")


def serve(app, port):
    uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")).run()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080, help="HTTP port; stream is port+1")
    a = ap.parse_args()
    print(f"mock ESP32-CAM: http://127.0.0.1:{a.port}/capture  stream http://127.0.0.1:{a.port + 1}/stream")
    threading.Thread(target=serve, args=(stream_api, a.port + 1), daemon=True).start()
    serve(api, a.port)

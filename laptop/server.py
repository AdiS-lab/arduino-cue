"""arduino-cue trigger server.

    python laptop\\server.py            (PowerShell; set env vars first, see README)

Endpoints: POST /trigger, GET /health, WS /ws, GET|POST /camera/settings, GET /preview.mjpg,
POST /speak, POST /send, GET /captures/*, GET / (AAC UI).
"""
import asyncio
import json
import socket
import time
import uuid
from contextlib import asynccontextmanager

import cv2
import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
import cv_adapter
import labels
import speak
from capture import Camera

PIPELINE_TIMEOUT_S = 4.5   # the ring (ESP32 / UNO Q) gives up after 5 s
SOURCES = {"ring", "ble_remote", "button", "keyboard", "ui", "clap"}
DEVICES = {"esp32cam", "unoq", "laptop"}

@asynccontextmanager
async def lifespan(_app):
    global camera, loop
    loop = asyncio.get_running_loop()
    camera = Camera(config.CAMERA_SOURCE)
    camera.on_status = lambda st: broadcast_threadsafe({"type": "status", "camera": st})
    camera.start()
    yield
    camera.stop()


app = FastAPI(title="arduino-cue", lifespan=lifespan)
camera: Camera = None
loop: asyncio.AbstractEventLoop = None
clients: set = set()
busy = False                 # touched only on the event loop -> no lock needed
events: list = []            # recent trigger events (for UI on connect)
recent: list = []            # recent detections


# ---------------------------------------------------------------- websocket
async def broadcast(msg: dict):
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


def broadcast_threadsafe(msg: dict):
    if loop is not None:
        asyncio.run_coroutine_threadsafe(broadcast(msg), loop)


async def log_event(source, status, ts, **extra):
    ev = {"type": "event", "source": source, "status": status, "ts": ts, "server_ts": int(time.time() * 1000), **extra}
    events.append(ev)
    del events[:-100]
    print(f"[event] {source:10s} {extra.get('device', ''):8s} {status:8s} {extra.get('label', '')}")
    await broadcast(ev)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"type": "status", "camera": camera.status(), "cv_mode": cv_adapter.mode(),
                        "ntfy": bool(config.NTFY_TOPIC), "events": events[-30:], "recent": recent[-12:],
                        "camera_source": config.CAMERA_SOURCE})
    try:
        while True:
            await ws.receive_text()   # we don't expect messages; keeps the socket open
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


# ---------------------------------------------------------------- trigger
def _pipeline(capture_id: str) -> dict:
    """Runs in a worker thread: burst -> CV -> result."""
    if not camera.status()["camera"]:
        raise RuntimeError("camera not available")
    frames, paths = camera.burst(capture_id)
    if not frames:
        raise RuntimeError("no frames from camera")
    cv_adapter.set_mock_hint(camera.current_source_name())
    result = cv_adapter.detect(frames)
    mid = paths[len(paths) // 2].name if paths else ""
    return {**result, "image_url": f"/captures/{mid}" if mid else ""}


DEVICE_BY_SOURCE = {"ring": "esp32cam", "button": "unoq", "clap": "unoq"}
HAPTIC_SOURCES = {"ble_remote", "keyboard", "ui"}   # the ring didn't send these, so tell it to vibrate
device_state = {"last_trigger": None, "last_haptic": None}


def _esp32():
    """The ESP32 source if the ring camera is in use, else None."""
    src = getattr(camera, "src", None)
    return src if src is not None and hasattr(src, "haptic") and getattr(src, "ip", "") else None


def send_haptic(pattern: str) -> dict:
    """Ask the ESP32 ring to vibrate. Never raises; result is shown in the UI Device panel."""
    esp = _esp32()
    if esp is None:
        res = {"ok": False, "pattern": pattern, "reason": "no ESP32 configured"}
    else:
        try:
            res = esp.haptic(pattern)
        except Exception as e:
            res = {"ok": False, "pattern": pattern, "reason": f"ESP32 unreachable ({type(e).__name__})"}
    device_state["last_haptic"] = {**res, "server_ts": int(time.time() * 1000)}
    return res


async def _finish(source, device, ts, resp, **extra):
    """Log the final event, forward haptics for non-ring triggers, return the HTTP response."""
    status = resp["status"]
    device_state["last_trigger"] = {"source": source, "device": device, "status": status,
                                    "label": resp["label"], "server_ts": int(time.time() * 1000)}
    await log_event(source, status, ts, device=device, capture_id=resp["capture_id"], label=resp["label"], **extra)
    if config.HAPTIC_FORWARD and source in HAPTIC_SOURCES and status != "busy":
        h = await asyncio.to_thread(send_haptic, "error" if status == "error" else status)
        await broadcast({"type": "device", **device_state, "haptic_result": h})
    return resp


@app.post("/trigger")
async def trigger(request: Request):
    global busy
    try:
        body = await request.json()
    except Exception:
        body = {}
    source = body.get("source") if body.get("source") in SOURCES else "ui"
    device = body.get("device") if body.get("device") in DEVICES else DEVICE_BY_SOURCE.get(source, "laptop")
    ts = body.get("ts") or int(time.time() * 1000)

    if busy:
        return await _finish(source, device, ts, {"status": "busy", "label": "", "confidence": 0.0, "capture_id": ""})

    busy = True
    capture_id = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    try:
        await log_event(source, "received", ts, device=device, capture_id=capture_id)
        t0 = time.time()
        err = {"status": "error", "label": "", "confidence": 0.0, "capture_id": capture_id}
        try:
            r = await asyncio.wait_for(asyncio.to_thread(_pipeline, capture_id), PIPELINE_TIMEOUT_S)
        except asyncio.TimeoutError:
            return await _finish(source, device, ts, err, error="timeout")
        except Exception as e:
            return await _finish(source, device, ts, err, error=str(e))

        status = "ok" if r["label"] else "none"
        disp = labels.display(r["label"])
        det = {"type": "detection", "status": status, "source": source, "device": device, "capture_id": capture_id,
               "label": r["label"], "confidence": r["confidence"], "word": disp["word"], "emoji": disp["emoji"],
               "image_url": r["image_url"], "ms": int((time.time() - t0) * 1000), "ts": ts}
        if status == "ok":
            recent.append(det)
            del recent[:-50]
            speak.say(disp["word"])
        await broadcast(det)
        return await _finish(source, device, ts, {"status": status, "label": r["label"],
                                                   "confidence": r["confidence"], "capture_id": capture_id})
    finally:
        busy = False


@app.get("/health")
def health():
    return {"ok": True, "camera": camera.status()["camera"], "cv_mode": cv_adapter.mode(),
            "camera_source": config.CAMERA_SOURCE}


# ---------------------------------------------------------------- device (ESP32 ring)
@app.get("/device")
def device_info():
    esp = _esp32()
    info, reachable = None, False
    if esp is not None:
        try:
            info, reachable = esp.cue_info(), True
        except Exception as e:
            info = {"error": type(e).__name__}
    return {"camera_source": config.CAMERA_SOURCE, "esp32_ip": getattr(esp, "ip", ""), "reachable": reachable,
            "info": info, **device_state}


@app.post("/device/haptic")
async def device_haptic(request: Request):
    pattern = str((await request.json()).get("pattern", ""))
    if pattern not in ("ok", "none", "error", "boot_fail"):
        raise HTTPException(400, "pattern must be ok|none|error|boot_fail")
    res = await asyncio.to_thread(send_haptic, pattern)
    await broadcast({"type": "device", **device_state})
    return res


# ---------------------------------------------------------------- camera
@app.get("/camera/settings")
def get_camera_settings():
    return {"settings": camera.get_settings(), "status": camera.status()}


@app.post("/camera/settings")
async def post_camera_settings(request: Request):
    try:
        updates = await request.json()
        res = camera.update_settings(updates)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    await broadcast({"type": "status", "camera": res["status"]})
    return res


def _mjpeg():
    last = -1
    while True:
        frame, fid = camera.latest()
        if frame is None or fid == last:
            time.sleep(0.03)
            continue
        last = fid
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        time.sleep(1 / 15)


@app.get("/preview.mjpg")
def preview():
    return StreamingResponse(_mjpeg(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/snapshot.jpg")
def snapshot():
    frame, _ = camera.latest()
    if frame is None:
        raise HTTPException(503, "no frame yet")
    ok, buf = cv2.imencode(".jpg", frame)
    return Response(buf.tobytes(), media_type="image/jpeg")


# ---------------------------------------------------------------- speech + messaging
@app.post("/speak")
async def speak_ep(request: Request):
    text = str((await request.json()).get("text", "")).strip()
    if not text:
        raise HTTPException(400, "text is required")
    queued = speak.say(text)
    await log_event("ui", "spoken", int(time.time() * 1000), label=text)
    return {"spoken": queued, "text": text, "tts_available": speak.available}


@app.post("/send")
async def send_ep(request: Request):
    text = str((await request.json()).get("text", "")).strip()
    if not text:
        raise HTTPException(400, "text is required")
    if not config.NTFY_TOPIC:
        return {"sent": False, "reason": "NTFY_TOPIC not set (offline mode)", "text": text}
    try:
        r = await asyncio.to_thread(requests.post, f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}",
                                    data=text.encode("utf-8"), headers={"Title": "Message from Cue"}, timeout=5)
        r.raise_for_status()
        await log_event("ui", "sent", int(time.time() * 1000), label=text)
        return {"sent": True, "text": text, "topic": config.NTFY_TOPIC}
    except Exception as e:
        return JSONResponse({"sent": False, "reason": str(e), "text": text}, status_code=502)


# ---------------------------------------------------------------- static
config.CAPTURES_DIR.mkdir(exist_ok=True)
app.mount("/captures", StaticFiles(directory=str(config.CAPTURES_DIR)), name="captures")


@app.get("/")
def index():
    return FileResponse(config.UI_DIR / "index.html")


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # no packet is sent; picks the default interface
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


if __name__ == "__main__":
    cam = f"esp32 @ {config.ESP32_IP or '(set ESP32_IP!)'}" if config.CAMERA_SOURCE == "esp32" else \
        f"{config.CAMERA_SOURCE} index={config.CAMERA_INDEX}"
    print(f"camera={cam} cv_mode={config.CV_MODE} "
          f"ntfy={'on' if config.NTFY_TOPIC else 'off'}")
    for ip in lan_ips():
        print(f"  UI:      http://{ip}:{config.PORT}/      <- open on phone (same hotspot)")
        print(f"  ring:    #define LAPTOP_IP \"{ip}\"  (esp32cam_firmware/secrets.h; UNO Q: LAPTOP_IP in main.py)  PORT {config.PORT}")
    print(f"  local:   http://127.0.0.1:{config.PORT}/")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")

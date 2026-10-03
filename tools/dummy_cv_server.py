"""A stand-in for the teammate's CV HTTP service (CV_MODE=http). It answers with a fixed or cycled label.

    python tools\\dummy_cv_server.py                  # listens on http://127.0.0.1:9000/detect
    $env:CV_MODE="http"; $env:CV_URL="http://127.0.0.1:9000/detect"; python laptop\\server.py

Contract: POST multipart/form-data with one or more files in field "frames" (JPEG).
Response: {"label": str, "confidence": float}
"""
import argparse
import itertools

import uvicorn
from fastapi import FastAPI, File, UploadFile

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=9000)
ap.add_argument("--labels", default="cup,apple,ball", help="comma list, cycled")
args, _ = ap.parse_known_args()
labels = itertools.cycle([s for s in args.labels.split(",") if s])

app = FastAPI()


@app.post("/detect")
async def detect(frames: list[UploadFile] = File(...)):
    sizes = [len(await f.read()) for f in frames]
    label = next(labels)
    print(f"[dummy-cv] got {len(frames)} frames {sizes} bytes -> {label}")
    return {"label": label, "confidence": 0.77}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")

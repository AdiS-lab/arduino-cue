"""Automated acceptance tests that need NO hardware (mock camera + mock CV).

    python tests\\acceptance.py            (PowerShell)    |    python3 tests/acceptance.py

Starts its own servers on ports 8101-8105 and prints PASS/FAIL per test.
The UI test (8) uses Playwright if it is installed (pip install playwright); otherwise it is skipped.
"""
import concurrent.futures as cf
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
sys.path.insert(0, str(ROOT / "tools"))
RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def start_server(port, **env):
    e = dict(os.environ, CAMERA_SOURCE="mock", PORT=str(port), PYTHONUNBUFFERED="1")
    e.update(env)
    p = subprocess.Popen([PY, str(ROOT / "laptop" / "server.py")], env=e, cwd=ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=1).ok:
                time.sleep(0.5)  # let the mock camera produce frames
                return p
        except Exception:
            time.sleep(0.25)
    p.kill()
    raise RuntimeError(f"server on {port} did not start:\n" + p.stdout.read().decode(errors="replace"))


def trig(port, source="ui"):
    return requests.post(f"http://127.0.0.1:{port}/trigger", json={"source": source, "ts": int(time.time() * 1000)}, timeout=8).json()


def snapshot_shape(port):
    import cv2
    import numpy as np
    time.sleep(0.4)
    b = requests.get(f"http://127.0.0.1:{port}/snapshot.jpg", timeout=3).content
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


class FakeNtfy(http.server.BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        FakeNtfy.received.append((self.path, self.rfile.read(int(self.headers["Content-Length"])).decode()))
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


def main():
    settings_file = ROOT / "camera_settings.json"
    had_settings = settings_file.exists()
    procs = []
    try:
        # 2. find_camera.py runs without crashing
        r = subprocess.run([PY, str(ROOT / "laptop" / "find_camera.py")], cwd=ROOT, capture_output=True, text=True, timeout=120)
        report("2 find_camera.py runs", r.returncode == 0, f"(exit {r.returncode})")

        procs.append(start_server(8101, CV_MODE="mock"))
        base = "http://127.0.0.1:8101"

        # 3. keyboard trigger -> label within 2 s, burst saved
        t0 = time.time()
        r = subprocess.run([PY, str(ROOT / "laptop" / "keyboard_trigger.py"), "--once", "--url", base + "/trigger"],
                           cwd=ROOT, capture_output=True, text=True, timeout=15)
        dt = time.time() - t0
        cid = r.stdout.split("id=")[1].split()[0] if "id=" in r.stdout else ""
        files = sorted((ROOT / "captures").glob(f"{cid}_*.jpg")) if cid else []
        ok = "-> ok" in r.stdout and dt < 2.0 + 1.0 and len(files) == 5  # +1 s python start-up overhead
        report("3 keyboard trigger -> label, burst saved", ok, f"{r.stdout.strip()} | {len(files)} files | {dt:.2f}s incl. process start")
        lat = time.time(); res = trig(8101); lat = time.time() - lat
        report("3b /trigger latency < 2 s", res["status"] == "ok" and lat < 2.0, f"{lat * 1000:.0f} ms label={res['label']}")

        # 4. /health 200; mock UNO Q -> ok + label
        h = requests.get(base + "/health")
        report("4a /health 200", h.status_code == 200 and h.json()["ok"], h.text)
        import mock_unoq
        u = mock_unoq.load_unoq("127.0.0.1", 8101)
        healthy = u.health_check_loop(max_tries=1)
        pat = u.handle_trigger("button", 1)
        report("4b mock_unoq -> ok + label (1 pulse)", healthy and pat == "ok" and u.Bridge.played[-1] == "ok")

        # 5. 5 rapid triggers -> exactly 1 processed
        with cf.ThreadPoolExecutor(5) as ex:
            sts = [x["status"] for x in ex.map(lambda _: trig(8101), range(5))]
        report("5 five rapid triggers -> 1 ok, 4 busy", sts.count("ok") == 1 and sts.count("busy") == 4, str(sts))

        # 6. /camera/settings round-trip + effect on preview
        s = requests.get(base + "/camera/settings").json()["settings"]
        f0 = snapshot_shape(8101)
        p = requests.post(base + "/camera/settings", json={"rotate": 90}).json()
        f1 = snapshot_shape(8101)
        p2 = requests.post(base + "/camera/settings", json={"rotate": 0, "zoom": 2.0}).json()
        f2 = snapshot_shape(8101)
        bad = requests.post(base + "/camera/settings", json={"rotate": 45})
        saved = json.loads(settings_file.read_text())
        ok = (p["settings"]["rotate"] == 90 and f0.shape[:2] == (480, 640) and f1.shape[:2] == (640, 480)
              and p2["settings"]["zoom"] == 2.0 and f2.shape[:2] == (480, 640) and bad.status_code == 400
              and saved["zoom"] == 2.0 and requests.get(base + "/camera/settings").json()["settings"]["zoom"] == 2.0)
        report("6 camera settings round-trip, rotate/zoom change preview, persisted, bad value -> 400", ok,
               f"shapes {f0.shape[:2]} -> {f1.shape[:2]} -> {f2.shape[:2]}")
        requests.post(base + "/camera/settings", json={"zoom": 1.0})

        # 7. CV_MODE=module and CV_MODE=http
        procs.append(start_server(8102, CV_MODE="module", CV_MODULE="examples.teammate_cv_stub:detect"))
        r = trig(8102)
        report("7a CV_MODE=module (examples/teammate_cv_stub.py)", r["status"] == "ok" and r["label"] == "cup", str(r))
        dummy = subprocess.Popen([PY, str(ROOT / "tools" / "dummy_cv_server.py"), "--port", "9101", "--labels", "ball"],
                                 cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(dummy)
        procs.append(start_server(8103, CV_MODE="http", CV_URL="http://127.0.0.1:9101/detect"))
        r = trig(8103)
        report("7b CV_MODE=http (tools/dummy_cv_server.py)", r["status"] == "ok" and r["label"] == "ball", str(r))

        # 8. Speak / Send with and without NTFY_TOPIC (+ UI via Playwright)
        sp = requests.post(base + "/speak", json={"text": "I want cup"}).json()
        report("8a /speak responds", sp["text"] == "I want cup" and "spoken" in sp, str(sp))
        sn = requests.post(base + "/send", json={"text": "I want cup"}).json()
        report("8b /send without NTFY_TOPIC -> sent:false", sn["sent"] is False and "NTFY_TOPIC" in sn["reason"], str(sn))
        ntfy = http.server.HTTPServer(("127.0.0.1", 9102), FakeNtfy)
        threading.Thread(target=ntfy.serve_forever, daemon=True).start()
        procs.append(start_server(8104, NTFY_TOPIC="cue-test", NTFY_SERVER="http://127.0.0.1:9102"))
        sn = requests.post("http://127.0.0.1:8104/send", json={"text": "Help"}).json()
        report("8c /send with NTFY_TOPIC -> posted to ntfy", sn["sent"] is True and FakeNtfy.received == [("/cue-test", "Help")], str(sn))
        ntfy.shutdown()
        ui_test(base)

        # 9. UNO Q app: laptop unreachable -> long pulse + log line
        u2 = mock_unoq.load_unoq("127.0.0.1", 8199)
        pat = u2.handle_trigger("button", 1)
        report("9 UNO Q 'laptop unreachable' -> 1 long pulse", pat == "error" and u2.Bridge.played == ["error"])

        esp32_tests(procs)
    finally:
        for p in procs:
            p.kill()
        if not had_settings and settings_file.exists():
            settings_file.unlink()
    fails = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} passed" + (f"; FAILED: {fails}" if fails else ""))
    sys.exit(1 if fails else 0)


def compile_test():
    """E1: compile both ESP32 sketches with arduino-cli if available (set ARDUINO_CLI to its path)."""
    import shutil
    import tempfile
    cli = os.environ.get("ARDUINO_CLI") or shutil.which("arduino-cli")
    if not cli:
        report("E1 ESP32 firmware compile (arduino-cli not found: NOT COMPILED, SKIPPED)", True)
        return
    extra = os.environ.get("ARDUINO_CLI_EXTRA", "").split()
    for sk in ("esp32cam_selftest", "esp32cam_firmware"):
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / sk
            shutil.copytree(ROOT / sk, dst)
            if (dst / "secrets.example.h").exists() and not (dst / "secrets.h").exists():
                shutil.copy(dst / "secrets.example.h", dst / "secrets.h")
            r = subprocess.run([cli, "compile", "-b", "esp32:esp32:esp32cam", *extra, str(dst)],
                               capture_output=True, text=True, timeout=1200)
            size = next((l for l in r.stdout.splitlines() if l.startswith("Sketch uses")), r.stderr[-300:])
            report(f"E1 {sk} compiles for esp32:esp32:esp32cam (UNTESTED ON HARDWARE)", r.returncode == 0, size)


def esp32_tests(procs):
    import cv2
    import numpy as np
    import mock_ring
    sys.path.insert(0, str(ROOT / "laptop"))
    mock = subprocess.Popen([PY, str(ROOT / "tools" / "mock_esp32_server.py"), "--port", "8150"], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(mock)
    m = "http://127.0.0.1:8150"
    for _ in range(40):
        try:
            requests.get(m + "/status", timeout=1); break
        except Exception:
            time.sleep(0.25)
    procs.append(start_server(8105, CAMERA_SOURCE="esp32", ESP32_IP="127.0.0.1", ESP32_HTTP_PORT="8150",
                              ESP32_STREAM_PORT="8151", CV_MODE="mock"))
    base = "http://127.0.0.1:8105"
    for _ in range(40):
        if requests.get(base + "/health").json()["camera"]:
            break
        time.sleep(0.25)
    h = requests.get(base + "/health").json()
    report("E2 /health reports camera_source=esp32 and camera up (mock ESP32)", h.get("camera_source") == "esp32" and h["camera"], str(h))

    # preview works: first MJPEG part decodes
    with requests.get(base + "/preview.mjpg", stream=True, timeout=5) as r:
        buf = b""
        for chunk in r.iter_content(8192):
            buf += chunk
            a, b = buf.find(b"\xff\xd8"), buf.find(b"\xff\xd9")
            if a >= 0 and b > a:
                break
    img = cv2.imdecode(np.frombuffer(buf[a:b + 2], np.uint8), cv2.IMREAD_COLOR)
    report("E3 preview.mjpg streams frames from ESP32 /stream", img is not None, f"{None if img is None else img.shape}")

    # snapshot burst (keyboard trigger) -> 5 frames saved + /haptic called with the result
    requests.post(m + "/_reset")
    r = trig(8105, "keyboard")
    files = sorted((ROOT / "captures").glob(f"{r['capture_id']}_*.jpg"))
    calls = requests.get(m + "/_calls").json()
    report("E4 CAMERA_SOURCE=esp32 snapshot burst saves 5 frames", r["status"] == "ok" and len(files) == 5, f"{r} files={len(files)}")
    report("E5 keyboard trigger -> ESP32 /haptic?pattern=ok", [c["pattern"] for c in calls["haptic"]] == ["ok"], str(calls["haptic"]))

    # ring button (mock_ring) -> ok + label, and NO /haptic call (the ring vibrates by itself)
    requests.post(m + "/_reset")
    time.sleep(0.2)
    pat = mock_ring.press(base, 1)
    calls = requests.get(m + "/_calls").json()
    ev = requests.get(base + "/device").json()["last_trigger"]
    report("E6 mock_ring.py -> ok + label, device=esp32cam, no /haptic echo", pat == "ok" and ev["device"] == "esp32cam"
           and ev["label"] and calls["haptic"] == [], f"{ev}")

    # ble_remote + ui -> /haptic
    import ble_remote
    requests.post(m + "/_reset")
    r1 = ble_remote.on_key("volume up", url=base + "/trigger")
    r_ignored = ble_remote.on_key("volume up", url=base + "/trigger")      # within cooldown -> ignored
    r_other = ble_remote.on_key("a", url=base + "/trigger", now=time.time() + 10)  # not a configured key
    r2 = trig(8105, "ui")
    calls = requests.get(m + "/_calls").json()
    report("E7 ble_remote (+cooldown, key filter) and ui triggers -> /haptic called", r1["status"] == "ok" and r_ignored is None
           and r_other is None and r2["status"] == "ok" and [c["pattern"] for c in calls["haptic"]] == ["ok", "ok"], str(calls["haptic"]))

    # /camera/settings forwards to ESP32 /control and changes the frames
    requests.post(m + "/_reset")
    res = requests.post(base + "/camera/settings", json={"framesize": 5, "quality": 20, "brightness": 1, "contrast": -1,
                                                       "hmirror": True, "vflip": False}).json()
    calls = requests.get(m + "/_calls").json()["control"]
    sent = {c["var"]: c["val"] for c in calls}
    props = res["status"]["props"]
    r = trig(8105, "keyboard")
    shot = cv2.imread(str(sorted((ROOT / "captures").glob(f"{r['capture_id']}_*.jpg"))[0]))
    ok = sent == {"framesize": 5, "quality": 20, "brightness": 1, "contrast": -1, "hmirror": 1, "vflip": 0} \
        and all(v["accepted"] for v in props.values()) and shot.shape[:2] == (240, 320)
    report("E8 /camera/settings forwards framesize/quality/brightness/contrast/hmirror/vflip to /control", ok,
           f"sent={sent} burst frame={shot.shape[:2]}")
    requests.post(base + "/camera/settings", json={"framesize": None, "quality": None, "brightness": None,
                                                   "contrast": None, "hmirror": None, "vflip": None})

    # haptic test button endpoint + ESP32 unreachable -> haptic fails gracefully, trigger -> error
    hres = requests.post(base + "/device/haptic", json={"pattern": "none"}).json()
    mock.kill(); time.sleep(0.5)
    hres2 = requests.post(base + "/device/haptic", json={"pattern": "error"}).json()
    report("E9 /device/haptic works; ESP32 down -> {ok:false} (no crash)", hres["ok"] and not hres2["ok"], f"{hres} / {hres2}")
    compile_test()


def ui_test(base):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report("8d UI (Playwright not installed: SKIPPED)", True)
        return
    exe = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe) if os.path.exists(exe) else pw.chromium.launch()
        page = b.new_page(viewport={"width": 390, "height": 844})  # phone-sized
        page.goto(base + "/")
        page.wait_for_selector("#p-ws.ok", timeout=5000)
        page.click("#capture")
        page.wait_for_function("document.querySelector('#det-word').textContent !== '—'", timeout=5000)
        word = page.inner_text("#det-word")
        log = page.inner_text("#log")
        page.click("#starters button:has-text('I want')")
        page.click("#recent button")
        sentence = page.inner_text("#sentence")
        page.click("#speak"); page.wait_for_function("document.querySelector('#msg').textContent.length > 0")
        spoke = page.inner_text("#msg")
        page.click("#send"); page.wait_for_function("document.querySelector('#msg').textContent.startsWith('Not sent')")
        sent = page.inner_text("#msg")
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        page.screenshot(path=str(ROOT / "docs" / "ui_phone.png"), full_page=True)
        page.set_viewport_size({"width": 1280, "height": 900})
        page.screenshot(path=str(ROOT / "docs" / "ui_laptop.png"))
        b.close()
    ok = word not in ("—", "nothing found") and "ok" in log and "I want" in sentence and spoke.startswith(("Speaking", "Not spoken")) \
        and "NTFY_TOPIC" in sent and not overflow
    report("8d UI: detection + event log via WS, sentence, Speak, Send (phone width, no h-scroll)", ok,
           f"word={word!r} sentence={sentence!r} speak={spoke!r} send={sent!r}")


if __name__ == "__main__":
    main()

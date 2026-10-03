# 👆 Cue: a smart-ring AAC aid

A nonverbal child points a finger-worn camera at an object and presses the ring button. The laptop captures a short
burst, a CV module labels the object, and the UI shows a word tile, speaks it, lets the child build a sentence, and can
send it to a caregiver's phone. The ring answers with a **vibration**.

**Offline** · **Private** (video lives only in memory, and nothing is saved until the button is pressed) · **Dedicated device**

```
PRIMARY  [ESP32-CAM ring, Wi-Fi]  button GPIO13 ─ POST /trigger ──────────────┐
                                  OV2640 ─ :81/stream (preview) + /capture (burst) ──► laptop/capture.py
[Laptop]  burst → cv_adapter.detect() → TTS + WebSocket → UI (laptop + phone) → HTTP response ─┐
[ESP32]   vibration motor GPIO14 ◄──── pattern from response (or GET /haptic for UI/keyboard/BT-remote triggers)
BACKUP   [UNO Q ring] button D2 → Bridge → Python → POST /trigger;  camera = Inland/C270 on laptop USB
OPTIONAL [Bluetooth ring remote] → laptop/ble_remote.py hotkey → /trigger (source "ble_remote")
```

> ⚠️ **UNTESTED ON HARDWARE:** `esp32cam_*`, `uno_q_app*`, `ble_remote.py`. What *was* verified:
> - Laptop code on Linux with mocks: `python tests/acceptance.py` → **24/24 pass** (mock camera, mock ESP32, mock CV).
> - Both ESP32 sketches **compile** with arduino-cli for `esp32:esp32:esp32cam` (core 3.3.1).
> - The UNO Q sketches only passed a compile against a minimal stand-in for the Arduino/Bridge API.

| Path | What |
|---|---|
| `esp32cam_selftest/` | **ESP32 hardware self-test**: button + motor. No Wi-Fi, no camera. **Flash this first.** |
| `esp32cam_firmware/` | **Ring firmware**: CameraWebServer (`/stream`, `/capture`, `/control`, `/status`) + button → `/trigger` + `/haptic` |
| `laptop/server.py` | FastAPI server: `/trigger`, `/health`, `/ws`, `/camera/settings`, `/preview.mjpg`, `/device`, `/speak`, `/send`, UI |
| `laptop/capture.py` | Camera layer: `esp32` (default) · `usb` (backup) · `mock` |
| `laptop/cv_adapter.py` | **CV plug-in point**. See [docs/CV_INTEGRATION.md](docs/CV_INTEGRATION.md) |
| `laptop/ble_remote.py` · `tools/detect_key.py` | Bluetooth ring-remote hotkey · key-name finder |
| `tools/mock_esp32_server.py` · `mock_ring.py` | Fake ESP32-CAM (stream/capture/control/haptic) · simulated ring button |
| `uno_q_app_selftest/` · `uno_q_app/` · `laptop/find_camera.py` | **Backup** wearable path (UNO Q + USB camera) |
| `docs/HARDWARE_NOTES.md` | Verified ESP32-CAM + UNO Q facts with sources; unconfirmed assumptions |

---

## 1. Install (PowerShell, Windows 11, Python 3.11+)
```powershell
cd arduino-cue
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
python tests\acceptance.py            # optional: no-hardware checks
```

## 2. Arduino IDE 2 + ESP32 core
1. Install **Arduino IDE 2**. Go to File → Preferences → *Additional boards manager URLs* and add
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
2. Boards Manager → install **esp32 by Espressif Systems**, version **3.x** (compiled here with 3.3.1).
3. Seat the ESP32-CAM on the **ESP32-CAM-MB** and connect it by USB (use a **data** cable). Select Tools → Board → esp32 → **AI Thinker ESP32-CAM**, then select the COM port.
   The default partition scheme (*Huge APP*) is fine. The firmware also ships the upstream `partitions.csv`.

## 3. Self-test the ring hardware (do this first, the moment parts arrive)
**Wiring** (Grove cable colours: **yellow = signal**, **red = power**, **black = GND**, **white = unused**):

| Part | Signal (yellow) | Power (red) | GND (black) |
|---|---|---|---|
| Button (Grove / module) | **GPIO13** | **3V3** | GND |
| Vibration motor **module** | **GPIO14** | **VCC** pin (5 V) | GND |

Leave **GPIO0 and GPIO12 unconnected** (boot strapping pins; GPIO0 is also the camera clock). Use the flash LED on GPIO4 only if needed (it is off by default).

**Run:** open `esp32cam_selftest/esp32cam_selftest.ino` → Upload → Serial Monitor at **115200**. Press **RST** on the MB board.
1. Boot gives **1 vibration pulse**, and the wiring summary prints (it repeats every 15 s).
2. Each press gives a **short pulse** and prints `BUTTON PRESSED #n`. Every raw change prints as `raw GPIO13 -> 0/1`.

| Symptom | Cause | Fix |
|---|---|---|
| No pulse at boot | Motor on wrong pin, no VCC, bare motor instead of module | Signal → GPIO14, red → VCC (5 V), black → GND. A **bare** motor needs a transistor driver, so use a motor *module* |
| Pulse OK, press prints nothing | Button not on GPIO13 / unpowered | Check `raw GPIO13` lines. If nothing prints, reseat the yellow wire on GPIO13 and red on 3V3 |
| Presses print on **release** / "PRESSED at boot" warning | Polarity inverted | Toggle `BUTTON_WIRING` (0 = Grove/module, active HIGH; 1 = bare button to GND) |
| Constant presses / "chattering" warning | Floating pin or loose GND | Bare button wired to GND → `BUTTON_WIRING = 1`. Module → check GND |
| Motor twitches at power-on | GPIO14 outputs PWM briefly during ESP32 boot | Harmless |

## 4. Flash the ring firmware
1. In `esp32cam_firmware/`, copy `secrets.example.h` → `secrets.h` and fill in the hotspot SSID and password (2.4 GHz!),
   plus `LAPTOP_IP` (printed by `server.py`, see step 6) and `LAPTOP_PORT` 8000. `secrets.h` is gitignored.
2. Open `esp32cam_firmware/esp32cam_firmware.ino` → Upload → Serial Monitor 115200 → press RST. It prints
   `Camera Ready! Use 'http://172.20.10.5' ...` and `Set on laptop: $env:ESP32_IP="172.20.10.5"`.
3. From the laptop (same hotspot), open `http://<ESP32_IP>` (upstream camera page) and `http://<ESP32_IP>:81/stream`.
   You should see live video. **Close that tab afterwards:** the ESP32 serves `:81/stream` to one client at a time, and the laptop needs it.

## 5. Move the ring to the power bank
1. Unplug USB and lift the ESP32-CAM off the MB board.
2. Power it from a power bank through a **cut USB cable**: **red → 5V pin**, **black → GND pin** (check with a multimeter, because some cables use other colours).
3. Wait about 5 s, then open `http://<ESP32_IP>:81/stream` again. It should still stream, at the same IP (the hotspot usually keeps it).

## 6. Run the server (ESP32 camera is the default)
```powershell
$env:ESP32_IP="172.20.10.5"; python laptop\server.py
```
It prints the UI URL and the exact `LAPTOP_IP` for `secrets.h`. Open `http://127.0.0.1:8000/` on the laptop and
`http://<laptop-ip>:8000/` on the phone. **Device** panel: "ring reachable", plus *Test ok/none/error* buttons that vibrate the ring.
**Camera settings** (ESP32 mode): ESP32 IP, burst mode, frame size, JPEG quality, brightness, contrast, mirror and flip.
These are forwarded to the ESP32 `/control`. Rotate, flip and zoom are applied on the laptop. Values persist to `camera_settings.json`, but an
explicitly set env var (e.g. `ESP32_IP`) wins.

Open the firewall once (admin PowerShell). The ESP32 and phone must be able to reach the laptop:
```powershell
New-NetFirewallRule -DisplayName "arduino-cue 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
```

## 7. End-to-end
Press the ring button. In the UI **Event log**, `ring esp32cam received` is followed by `ring esp32cam ok cup`. The word appears, the laptop says it,
and the ring vibrates **once**.

| Ring vibration | Meaning |
|---|---|
| 1 pulse at power-on | Booted |
| 3 pulses, repeating every 5 s | Laptop `/health` unreachable (wrong `LAPTOP_IP`, server off, firewall, other Wi-Fi) |
| 1 × 150 ms | Word found |
| 2 × 100 ms | Nothing recognised |
| nothing | Busy (a capture is already running) |
| 1 × 600 ms | Error / > 5 s / laptop unreachable (Serial: `BUTTON OK, LAPTOP UNREACHABLE`) |

Triggers from the **UI Capture button, keyboard or Bluetooth remote** also vibrate the ring: the laptop calls `GET /haptic?pattern=…` on the ESP32.

## 8. Test without hardware
```powershell
# fake ESP32-CAM on :8080 (+ stream on :8081)
python tools\mock_esp32_server.py
# server against it
$env:ESP32_IP="127.0.0.1"; $env:ESP32_HTTP_PORT="8080"; $env:ESP32_STREAM_PORT="8081"; python laptop\server.py
# simulated ring button / keyboard
python tools\mock_ring.py
python laptop\keyboard_trigger.py
# or no camera at all:
$env:CAMERA_SOURCE="mock"; python laptop\server.py
```

## 9. Optional: Bluetooth ring remote
Pair a BT camera-shutter / media ring in Windows Bluetooth settings (it acts as a keyboard). Then run:
```powershell
python tools\detect_key.py            # press the remote, note the key name (e.g. 'volume up')
$env:BLE_KEYS="volume up"; python laptop\ble_remote.py
```
The default `BLE_KEYS` is `volume up,enter`. "enter" is global, so remove it if the laptop is also used for typing. Volume Up is suppressed so it
doesn't change the volume. Each press triggers a capture and vibrates the ESP32 ring with the result.

## 10. Plug in the teammate's CV
`$env:CV_MODE="module"; $env:CV_MODULE="teammate_cv.detector:detect"` or `$env:CV_MODE="http"; $env:CV_URL="http://…/detect"`.
See **[docs/CV_INTEGRATION.md](docs/CV_INTEGRATION.md)**.

## 11. 60-second demo script
1. **(0:00)** "Maya is nonverbal. Picture boards are slow, and phones are distracting. Cue is a camera ring."
2. **(0:10)** Show the phone UI: live view from the ring. "Nothing is recorded, it's only in memory."
3. **(0:20)** Point the ring at a cup and **press**. *Bzz.* The tile says **cup**, and the laptop says "cup".
4. **(0:30)** Tap **I want** + **cup** → **Speak**: "I want cup."
5. **(0:40)** **Send**, and the caregiver's phone buzzes (ntfy, opt-in). Everything else is offline.
6. **(0:50)** Point at nothing and press: *bz-bz* = "didn't recognise, try again." Close: offline, private, dedicated.

Backup: if the ESP32 misbehaves, run `$env:CAMERA_SOURCE="usb"` with the Inland/C270 (section B), or `$env:CAMERA_SOURCE="mock"`.

---

## B. BACKUP path: UNO Q ring + USB camera (Inland endoscope / Logitech C270)
Use this if the ESP32-CAM fails. The camera plugs into the **laptop**, and the UNO Q is a wireless button + vibration motor.

**B1. UNO Q first-time setup (USB-C, once).** Install **Arduino App Lab**. Connect with a data USB-C cable, and the setup wizard runs. Set
the board name, Wi-Fi = **phone hotspot** (WPA2; captive portals not supported) and the Linux password for user `arduino`. Then copy
`uno_q_app_selftest/` and `uno_q_app/` onto the board, either as Apps of the same name in App Lab, or `scp -r` to `/home/arduino/ArduinoApps/`.
After Wi-Fi is set, App Lab **Network Mode** (Wi-Fi icon) works without the cable. Allow `mdns-discovery.exe` through the firewall when asked.

**B2. Self-test.** Wiring at **3.3 V**:

| Part | Grove Base Shield V2 (switch at **3V3**) | Direct jumper wires |
|---|---|---|
| Button | port **D2** | SIG → D2, VCC → 3.3V, GND → GND (bare button: D2↔GND, `BUTTON_WIRING = 1`) |
| Vibration motor **module** | port **D3** | SIG → D3, VCC → 3.3V/5V per module, GND → GND |
| Sound sensor (optional) | port **A0** | SIG → A0, VCC → 3.3V, GND → GND |

Run **arduino-cue self-test** in App Lab, then open Console → **Serial Monitor**. Expect 1 pulse at boot, and each press gives a pulse + LED flash +
`BUTTON PRESSED #n`. For the sound sensor, set `SOUND_SENSOR_CONNECTED = true` and watch `A0 = …`. A clap gives a double pulse.

| Symptom | Fix |
|---|---|
| No pulse at boot | Motor module on D3, powered, shield at 3V3, reseat Grove cable |
| Press shows no print | Watch the `raw D2` lines. Reseat the cable / try another port and change `BUTTON_PIN` |
| Constant presses / chattering | Bare button with `BUTTON_WIRING = 0` → set it to 1. Check GND |
| Press registers on release | Toggle `BUTTON_WIRING` |
| A0 stuck at 0 / at max | Check power and that you used the analog pin. Turn the module pot. Tune `CLAP_THRESHOLD` |

**B3. Camera.** Plug the Inland into the laptop, then run `python laptop\find_camera.py` and compare the `probe\` snapshots to pick the index.
```powershell
$env:CAMERA_SOURCE="usb"; $env:CAMERA_INDEX="1"; python laptop\server.py
```
Keep objects **3–10 cm** from the endoscope tip.

**B4. Go wireless.** Set `LAPTOP_IP` in `uno_q_app/python/main.py`, run **arduino-cue** in App Lab and enable **Run at Startup**, then power it
from the power bank. Check from the UNO Q shell (`ssh arduino@<board>.local`): `curl http://<LAPTOP_IP>:8000/health`.
`python tools\mock_unoq.py` simulates this ring on the laptop. Vibration meanings are the same as in step 7.

---

## Debugging
| Problem | Fix |
|---|---|
| **ESP32 upload fails** ("Failed to connect", "Timed out waiting for packet header") | On the MB board: **hold IO0, tap RST, release IO0**, then upload. Pick the right COM port. Use a data cable. Lower the upload speed to 115200. |
| **"Camera init failed with error 0x…"** | Reseat the camera ribbon (latch closed, contacts the right way round). Check power (brownout). The board must be **AI Thinker ESP32-CAM**. The ring still vibrates a long pulse and the button keeps working. |
| **Brownout / random resets** ("Brownout detector was triggered") | Power bank ≥ 1 A, short thick wires, 5V pin (not 3V3). The motor peak adds current, which is why the pulses are short. |
| **Board won't boot / stuck in download mode** | Nothing may be connected to **GPIO0 or GPIO12**. Remove the IO0 jumper/button. Press RST. |
| **Stream won't load** | Same hotspot? Is the ESP32 IP still the same (Serial Monitor)? Use **2.4 GHz** (the ESP32 has no 5 GHz). Only one client can view `:81/stream` well at a time: close the upstream web page if the laptop preview stalls. |
| **Ring can't reach laptop** (3 pulses repeating) | Wrong `LAPTOP_IP` in `secrets.h` (check `ipconfig`) or the firewall rule from step 6 is missing. Hotspots are often a "Public" profile, so use `-Profile Any`. |
| **Laggy stream / slow burst** | Keep `burst_mode = snapshot`. Lower `framesize` to QVGA/VGA. Raise JPEG `quality` (number) to 12–20. Move closer to the phone. |
| **Inverted button** | Toggle `BUTTON_WIRING` (0 ↔ 1) in the sketch. |
| **No haptic** | Use a motor **module** (driver on board), not a bare motor on a GPIO. Its red wire goes to **VCC (5 V)**. Test with the UI *Test ok* button and self-test. |
| UI says "ESP32_IP not set" | `$env:ESP32_IP="…"` before starting, or type it in Camera settings → ESP32 IP. |
| USB camera not detected / black / wrong lens (backup) | Run `find_camera.py`. Try MSMF. Check Windows camera privacy. Try the C270. Properties marked "IGNORED" are not supported by that camera. |
| UNO Q not seen by App Lab (backup) | Data USB-C cable. Same network + mDNS for Network Mode. Use **Run at Startup** for power-bank use. |
| Power bank switches off | Low-current auto-off. Use an always-on mode, or charge something else from it at the same time. |
| No speech | Windows SAPI5 volume/output device. `$env:TTS_ENABLED="0"` disables it. |
| Send says "NTFY_TOPIC not set" | Expected offline. `$env:NTFY_TOPIC="cue-<random>"` and subscribe in the ntfy app. |

## Config reference (`laptop/config.py`, all env vars)
`CAMERA_SOURCE` esp32|usb|mock · `ESP32_IP` · `ESP32_HTTP_PORT` 80 · `ESP32_STREAM_PORT` 81 · `BURST_MODE` snapshot|stream ·
`HAPTIC_FORWARD` 1 · `CAMERA_INDEX` · `CAMERA_BACKEND` · `BURST_N` 5 · `BURST_GAP_MS` 100 · `CV_MODE` mock|module|http ·
`CV_MODULE` · `CV_URL` · `MOCK_LABELS` · `TTS_ENABLED` · `NTFY_TOPIC` · `PORT` 8000 · `BLE_KEYS` · `BLE_SUPPRESS`

Compile check (optional, if you have arduino-cli): `arduino-cli compile -b esp32:esp32:esp32cam esp32cam_firmware`
(needs a `secrets.h`). `tests\acceptance.py` does this automatically when `arduino-cli` is on PATH or `ARDUINO_CLI` is set.

# 👆 Cue: a smart-ring AAC aid

A nonverbal child points a finger-mounted camera at an object and presses the ring button. The laptop captures a
short burst, a CV module labels the object, and the UI shows a word tile, speaks it, lets the child build a sentence,
and can send that sentence to a caregiver's phone.

**Offline** · **Private** (the camera streams into memory only, and nothing is saved until the button is pressed) · **Dedicated device**

```
[UNO Q, wireless]  Button D2 → MCU sketch → Bridge → UNO Q Python → HTTP POST /trigger ─┐
[Laptop]  Inland endoscope cam → capture.py (always-on, in memory) → burst → cv_adapter.detect()
          → TTS + WebSocket → UI (laptop + phone)  → HTTP response ─┐
[UNO Q]   Python → Bridge → MCU beep pattern   ◄─────────────────────┘
```

> ⚠️ Everything under `uno_q_app*/` is **UNTESTED ON HARDWARE**. All laptop code was tested on Linux with the mock camera
> (`python tests/acceptance.py`: 14/14 pass), not on Windows with a real camera.

| Path | What |
|---|---|
| `uno_q_app_selftest/` | **Hardware self-test** App: button / buzzer / sound sensor. No laptop, no network. |
| `uno_q_app/` | Main wireless button App (sketch + Python). One config line: `LAPTOP_IP`. |
| `laptop/server.py` | FastAPI server: `/trigger`, `/health`, `/ws`, `/camera/settings`, `/preview.mjpg`, `/speak`, `/send`, UI |
| `laptop/capture.py` · `find_camera.py` | Camera layer (USB/mock) · camera index scanner |
| `laptop/cv_adapter.py` | **CV plug-in point** for the teammate. See [docs/CV_INTEGRATION.md](docs/CV_INTEGRATION.md) |
| `laptop/config.py` | All laptop settings (env-var overridable) |
| `ui/index.html` | AAC UI (single file, no build) |
| `tools/mock_unoq.py` · `dummy_cv_server.py` | Simulated ring button · fake CV HTTP service |
| `docs/UNO_Q_NOTES.md` | Verified UNO Q / App Lab / Bridge facts with sources; unconfirmed assumptions |

---

## 1. Install (PowerShell, Windows 11, Python 3.11+)
```powershell
cd arduino-cue
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
python tests\acceptance.py            # optional: 14 no-hardware checks
```

## 2. UNO Q first-time setup (USB-C, once)
1. Install **Arduino App Lab** on the laptop. Plug the UNO Q in with a **data** USB-C cable (charge-only cables won't show the board).
2. App Lab detects the board and runs the setup wizard: board name, **Wi-Fi = your phone hotspot** (WPA2; captive portals are not supported), and a Linux password for user `arduino`.
   Write the password down, because Network Mode and SSH need it.
3. Copy `uno_q_app_selftest/` and `uno_q_app/` onto the board. Either create Apps of the same name in App Lab and paste in
   `sketch/sketch.ino` + `python/main.py`, or copy the folders to `/home/arduino/ArduinoApps/` (e.g. `scp -r uno_q_app arduino@<board>.local:ArduinoApps/`).
4. After Wi-Fi is set up, App Lab can also reach the board in **Network Mode** (Wi-Fi icon next to the board, mDNS + SSH). When Windows asks, allow `mdns-discovery.exe` through the firewall.

## 3. Hardware self-test (do this first, the moment parts arrive)
**Wiring.** All modules run at **3.3 V** (UNO Q I/O is 3.3 V).

| Part | Grove Base Shield V2 (switch set to **3V3**) | Direct jumper wires |
|---|---|---|
| Button | Grove cable into port **D2** | SIG → D2, VCC → 3.3V, GND → GND (bare 2-leg button: one leg D2, other leg GND, and set `BUTTON_WIRING = 1`) |
| Buzzer | port **D3** | SIG → D3, VCC → 3.3V, GND → GND |
| Sound sensor (optional) | port **A0** | SIG → A0, VCC → 3.3V, GND → GND |

**Run.** In App Lab, open **arduino-cue self-test** → ▶ Run → Console → **Serial Monitor** tab.
1. You should hear **1 short beep** at start, and the wiring summary prints (it repeats every 15 s).
2. Press the button: **beep + LED flash + `BUTTON PRESSED #1`**. Every raw pin change also prints as `raw D2 -> 0/1`.
3. Sound sensor (optional): set `SOUND_SENSOR_CONNECTED = true` and run again. `A0 = …` prints every 200 ms, and a clap gives a double beep + `CLAP <v>`.

| Symptom | Likely cause | Fix |
|---|---|---|
| No beep at boot | Buzzer on wrong pin, VCC/GND swapped, shield not at 3V3, loose Grove cable | Reseat the cable in D3. Check the shield's 3V3/5V switch. Swap the buzzer module. (Both buzzer types are supported: the sketch sends a 2 kHz square wave) |
| Boot beep OK, but a press shows no print / no beep | Button not on D2, no power to the module, or Monitor tab not open | Check `raw D2` lines. If none appear on press, the wiring is wrong. Reseat the Grove cable, then try another Grove port and change `BUTTON_PIN` |
| Constant presses / `raw D2` flapping / "chattering" warning | Floating pin (bare button with `BUTTON_WIRING = 0`) or loose GND | Bare button wired to GND → set `BUTTON_WIRING = 1`. Module → check the GND wire |
| "PRESSED at boot" warning, or a press prints only on *release* | Polarity inverted | Toggle `BUTTON_WIRING` (0 ↔ 1) |
| A0 stuck at 0 | Sensor unpowered / wrong pin | Check VCC + GND and that SIG is on A0. Some modules have a sensitivity pot, so turn it |
| A0 stuck near max (~1023) | Wrong pin / digital-out sound module / pot maxed | Use the analog (AO) pin of the module. Turn the pot down. Adjust `CLAP_THRESHOLD` |

## 4. Camera: find the right index
Plug the Inland endoscope into the **laptop**. Windows should show it as a webcam. Then run:
```powershell
python laptop\find_camera.py
```
Open the `probe\` folder: there's one snapshot per working `index` × backend. A dual-lens endoscope may show up as two indices (one per lens). Pick the one that shows what's in front of the **tip** lens.
```powershell
$env:CAMERA_INDEX="1"   # whichever index looked right
```
(You can also change the index live in the UI under **Camera settings**.)

## 5. Run the server and open the UI
```powershell
$env:CAMERA_INDEX="1"; python laptop\server.py
```
It prints the UI URL and the exact `LAPTOP_IP` line for the UNO Q. Open `http://127.0.0.1:8000/` on the laptop and
`http://<laptop-ip>:8000/` on the phone (same hotspot). Under **Camera settings**, tune rotate / flip / zoom / exposure
while you watch the live preview. Settings persist to `camera_settings.json`. The panel shows the actual resolution and which
camera properties the device **accepted vs ignored**. Keep objects **3–10 cm** from the endoscope tip for focus.

## 6. Test without hardware
```powershell
# terminal 1 (mock camera + mock CV):
$env:CAMERA_SOURCE="mock"; $env:CV_MODE="mock"; python laptop\server.py
# terminal 2:
python laptop\keyboard_trigger.py          # Enter/Space = capture
python tools\mock_unoq.py                  # simulated ring: Enter = button press, prints the beeps
python tools\mock_unoq.py --presses 3
```

## 7. Plug in the teammate's CV
`$env:CV_MODE="module"; $env:CV_MODULE="teammate_cv.detector:detect"` or `$env:CV_MODE="http"; $env:CV_URL="http://…/detect"`.
See **[docs/CV_INTEGRATION.md](docs/CV_INTEGRATION.md)**.

## 8. UNO Q goes wireless
1. Get the laptop's hotspot IP (printed by `server.py`, or `ipconfig` → Wi-Fi adapter → IPv4).
2. Edit `uno_q_app/python/main.py`: `LAPTOP_IP = "…"` (and `PORT` if changed). This is the only config line.
3. Open the firewall port once (admin PowerShell):
   ```powershell
   New-NetFirewallRule -DisplayName "arduino-cue 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
   ```
4. Run **arduino-cue** in App Lab, then **▼ next to the App name → Run at Startup**.
5. Unplug from the laptop and power the UNO Q from a power bank. Wait about 1 minute for Linux to boot and the App to start.
6. Verify from the UNO Q shell (App Lab terminal or `ssh arduino@<board-name>.local`):
   ```bash
   curl http://<LAPTOP_IP>:8000/health      # -> {"ok":true,"camera":true,"cv_mode":"mock"}
   ```
   3 short beeps repeating every 5 s = the UNO Q cannot reach `/health` (see Debugging).

## 9. End-to-end
Press the ring button. The UI **Event log** shows `button received` → `button ok cup`, the detection card shows the word,
the laptop speaks it, and the ring plays **1 short beep**.

| Ring beep | Meaning |
|---|---|
| 1 short at power-on | MCU alive |
| 3 short, repeating | Laptop `/health` unreachable (boot) |
| 1 short | Word found |
| 2 short | Nothing recognised |
| none | Busy (capture in progress) |
| 1 long | Error / > 5 s / laptop unreachable (`BUTTON OK, LAPTOP UNREACHABLE` in the Python log) |

## 10. 60-second demo script
1. **(0:00)** "Maya is nonverbal. Picture boards are slow, and phones are distracting. Cue is a ring with a camera."
2. **(0:10)** Show the phone UI: live preview from the ring. "Nothing is recorded, it's only in memory."
3. **(0:20)** Point the ring at a cup and **press the button**. *Beep.* The tile says **cup**, and the laptop says "cup".
4. **(0:30)** Tap **I want** + **cup** → **Speak**: "I want cup."
5. **(0:40)** Tap **Send**, and the caregiver's phone buzzes (ntfy). "All offline except this opt-in message."
6. **(0:50)** Point at nothing and press: *beep beep* = "I didn't recognise that, try again." Close on the pitch pillars: offline, private, dedicated.

Backup plan: if the camera or CV misbehaves, run with `CAMERA_SOURCE=mock` (and `MOCK_LABELS="cup,apple,ball"`). The rest of the demo is identical.

---

## Debugging
| Problem | Fix |
|---|---|
| Inland endoscope not detected as a webcam | Try another USB port and the USB-C↔A adapter. Check Settings → Privacy → Camera → allow desktop apps. Close other camera apps (Teams/Zoom). Use the **Logitech C270** backup (same steps, run `find_camera.py`). |
| Wrong lens / wrong index | Run `find_camera.py`, compare `probe\index*_*.jpg`, set `CAMERA_INDEX` or switch it in the UI. Some dual-lens models switch lens with a button on the cable. |
| Black frames | Status shows "BLACK FRAMES". Usually the wrong index (e.g. a virtual or IR camera), the endoscope LEDs are off, or it needs more light. Raise `warmup_frames`. Try backend MSMF. |
| Stale / frozen preview | The server reopens the camera after 3 failed reads (`reconnects` count in the UI). Replug the cable. Changing the index or backend in the UI forces a reopen. |
| Out of focus | Endoscope focus is fixed at about 3–10 cm (1.2–4 in). Move the object closer or further. Digital zoom only crops. |
| Brightness/exposure "IGNORED" | Many UVC cameras ignore some properties. The UI shows the readback. Try the other backend (DSHOW ↔ MSMF), or switch auto exposure on. |
| Phone / UNO Q can't reach the laptop | Add the firewall rule from step 8. Hotspots are often a "Public" network profile, so use `-Profile Any`. Make sure **all** devices are on the **phone hotspot**, not campus Wi-Fi (it blocks device-to-device traffic). Check the IP again with `ipconfig`, because the hotspot can hand out a new one. |
| `curl` from UNO Q hangs | Wrong `LAPTOP_IP`, the server isn't running, or the firewall. From the UNO Q, run `ping <LAPTOP_IP>`. |
| Button polarity | Self-test step 3 table: toggle `BUTTON_WIRING` in the sketch (both apps). |
| Grove module flaky | Reseat both ends of the Grove cable. The Base Shield switch must be at **3V3**. Try another port and update the pin constant. |
| UNO Q not seen by App Lab | Use a data USB-C cable (charge-only cables are common). Try another port. In Network Mode the board must be on the same network as the laptop with mDNS allowed. |
| UNO Q dies after ~30 s on the power bank | The bank auto-shuts off at low current. Use a bank with an always-on or low-current mode, or charge something else from it at the same time. |
| App doesn't start on power-up | Set **Run at Startup** (only one App can be the startup App). |
| No speech | `pyttsx3` uses Windows SAPI5. Check the volume and output device. Set `$env:TTS_ENABLED="0"` to disable. |
| Send says "NTFY_TOPIC not set" | Expected offline behaviour. To enable: `$env:NTFY_TOPIC="cue-<random>"` and subscribe to that topic in the ntfy phone app (needs internet on the hotspot). |

## Config reference (`laptop/config.py`, all env vars)
`CAMERA_SOURCE` usb|mock · `CAMERA_INDEX` 0–4 · `CAMERA_BACKEND` DSHOW|MSMF · `CAMERA_WIDTH/HEIGHT` · `CAMERA_MJPG` ·
`WARMUP_FRAMES` 10 · `BURST_N` 5 · `BURST_GAP_MS` 100 · `CV_MODE` mock|module|http · `CV_MODULE` · `CV_URL` · `MOCK_LABELS` ·
`TTS_ENABLED` · `NTFY_TOPIC` · `NTFY_SERVER` · `PORT` 8000 · `HOST` 0.0.0.0

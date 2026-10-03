# Hardware notes (verified)

Two wearables share one laptop server:
- **PRIMARY: AI Thinker ESP32-CAM (OV2640)**: camera + button + vibration motor on one board, over Wi-Fi.
- **BACKUP: Arduino UNO Q + USB camera** (Inland endoscope / Logitech C270 on the laptop).

Legend: ✅ CONFIRMED in official source · ⚠️ UNCONFIRMED (assumption; isolated in one place)

---

# AI Thinker ESP32-CAM (PRIMARY): verified notes

Verified on 2026-10-03 against **espressif/arduino-esp32 @ `aeabde6e`** (master, 2026-10-02):
https://github.com/espressif/arduino-esp32/tree/master/libraries/ESP32/examples/Camera/CameraWebServer

| File | What it confirms |
|---|---|
| [`camera_pins.h`](https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h) | AI Thinker pin map ✅ |
| [`app_httpd.cpp`](https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/app_httpd.cpp) | Endpoints, ports, `/control` vars, `/status` JSON ✅ |
| [`CameraWebServer.ino`](https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/CameraWebServer.ino) | Camera init (PSRAM → `fb_count=2`, `CAMERA_GRAB_LATEST`), Wi-Fi setup ✅ |
| [`ci.yml`](https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/ci.yml) / `partitions.csv` | Needs a ≥3 MB app partition. We ship the upstream `partitions.csv` ✅ |

### AI Thinker pin map ✅ (from `camera_pins.h`)
| Signal | GPIO | | Signal | GPIO |
|---|---|---|---|---|
| PWDN | 32 | | Y9 | 35 |
| RESET | -1 (none) | | Y8 | 34 |
| **XCLK** | **0** | | Y7 | 39 |
| SIOD (SDA) | 26 | | Y6 | 36 |
| SIOC (SCL) | 27 | | Y5 | 21 |
| VSYNC | 25 | | Y4 | 19 |
| HREF | 23 | | Y3 | 18 |
| PCLK | 22 | | Y2 | 5 |
| **LED flash** | **4** | | | |

So **GPIO0 is the camera clock and a strapping pin**: never connect anything there. GPIO12 is a strapping pin (flash voltage), so leave it free too.
**GPIO13 and GPIO14 are free** when the microSD slot is unused, and arduino-cue does not use the SD card. These are the ring's button and motor pins.

### Endpoints ✅ (from `app_httpd.cpp` `startCameraServer()`)
| Port | URI | Notes |
|---|---|---|
| 80 | `/` | Upstream web UI (OV2640 page) |
| 80 | `/capture` | One JPEG. Turns the flash on for ~150 ms first, at `led_intensity` (default **0 = off**) |
| 80 | `/control?var=<name>&val=<int>` | `framesize, quality, contrast, brightness, saturation, gainceiling, colorbar, awb, agc, aec, hmirror, vflip, awb_gain, agc_gain, aec_value, aec2, dcw, bpc, wpc, raw_gma, lenc, special_effect, wb_mode, ae_level, led_intensity`. Unknown var → HTTP 500 |
| 80 | `/status` | JSON incl. `framesize, quality, brightness, contrast, hmirror, vflip, led_intensity` |
| 80 | `/bmp`, `/xclk`, `/reg`, `/greg`, `/pll`, `/resolution` | Kept, unused by arduino-cue |
| **81** | `/stream` | MJPEG (`multipart/x-mixed-replace`). The stream server runs on `server_port + 1` |
| 80 | **`/haptic?pattern=ok\|none\|error\|boot_fail`** | **arduino-cue addition** (`esp32cam_firmware.ino`) |
| 80 | **`/cue`** | **arduino-cue addition**: `{"device","presses","laptop_reachable","laptop","rssi","uptime_s"}` |

`max_uri_handlers = 16`. Upstream registers 10 on :80, and we add 2.
OV2640 `framesize` values (esp32-camera enum): 5=QVGA 320×240, 8=VGA 640×480, 9=SVGA 800×600, 10=XGA 1024×768, 13=UXGA 1600×1200.
`quality` is JPEG quality 4–63 (lower = better). `brightness` and `contrast` take -2…2.

### Build ✅ (compiled with arduino-cli during development; NOT flashed to hardware)
`arduino-cli compile -b esp32:esp32:esp32cam` with **esp32 core 3.3.1**:
- `esp32cam_firmware`: 1,226,007 B flash (38%), 70,712 B RAM.
- `esp32cam_selftest`: 313,419 B flash (9%).

Both compile. The firmware uses core-3.x APIs (`ledcAttach` in upstream `app_httpd.cpp`), so **use esp32 core ≥ 3.0**.

### Assumptions ⚠️ (UNTESTED ON HARDWARE)
| Assumption | Where |
|---|---|
| GPIO14 briefly outputs a PWM signal at boot (common ESP32 behaviour), so the motor may twitch at power-on. This is harmless. | n/a |
| The Grove button works at 3.3 V on GPIO13 with `INPUT_PULLDOWN` (active HIGH). Bare button: `BUTTON_WIRING = 1`. | `BUTTON_WIRING` in both ESP32 sketches |
| The motor **module** (has a driver transistor) is OK on VCC (5 V from the power bank) with a 3.3 V signal on GPIO14. A **bare** motor must NOT be driven directly from a GPIO. | wiring in README |
| `HTTPClient` 5 s timeouts (`setConnectTimeout` + `setTimeout`) behave as expected. The HTTP call runs in its own FreeRTOS task, so haptics and the button stay responsive. | `triggerTask()` in `esp32cam_firmware.ino` |
| A power bank on 5V/GND supplies the Wi-Fi + camera current peaks (~300+ mA). Brownouts would show as resets in the Serial log. | README debugging |

---

# Arduino UNO Q (BACKUP wearable): verified notes

Verified on 2026-10-03 against the **official Arduino sources on GitHub**. `docs.arduino.cc` and
`forum.arduino.cc` were blocked by the build environment's network proxy. The same pages were read
from their source repo, `arduino/docs-content`, and the official example apps were read from `arduino/app-bricks-examples`.

Legend: ✅ CONFIRMED in official docs or examples · ⚠️ UNCONFIRMED (assumption; isolated behind one function)

## Sources
| Topic | Source (docs.arduino.cc path ← docs-content file) |
|---|---|
| Bridge API reference | https://docs.arduino.cc/software/app-lab/bridge/bridge-api/ ← `content/software/app-lab/6.bridge/2.bridge-api/bridge-api.md` |
| App anatomy | https://docs.arduino.cc/software/app-lab/apps/about-apps/ ← `4.apps/1.about-apps/about-apps.md` |
| Run / Monitor / Run at Startup | https://docs.arduino.cc/software/app-lab/apps/run/ ← `4.apps/6.run/run.md` |
| Board setup, USB vs Network mode | https://docs.arduino.cc/software/app-lab/configure/config/ ← `2.configure/1.config/config.md` |
| Network ports / mDNS | https://docs.arduino.cc/software/app-lab/configure/network-configuration/ ← `2.configure/3.network-configuration/network-configuration.md` |
| CLI (`arduino-app-cli`) | https://docs.arduino.cc/software/app-lab/cli/commands/ ← `7.cli/2.commands/commands.md` |
| Example apps | https://github.com/arduino/app-bricks-examples (`core-and-foundational/03-bridge-basics/*`, `04-logging/02-mcu-monitor`, `inspirational/common/air-quality-monitoring`) |

## App structure ✅
```
my_app/
  app.yaml              # mandatory: name, icon, description (+ bricks, managed by App Lab)
  python/main.py        # mandatory: Linux-side entry point, must end with App.run(...)
  python/requirements.txt  # optional pip deps (must be inside python/)
  sketch/sketch.ino     # optional MCU sketch
  sketch/sketch.yaml    # mandatory if sketch exists (platform arduino:zephyr)
```
Apps live on the board in `/home/arduino/ArduinoApps/`. A minimal `app.yaml` from the official examples:
```yaml
name: App Run
icon: ▶️
description: ...
```
`sketch.yaml` (verbatim from the examples):
```yaml
profiles:
  default:
    platforms:
      - platform: arduino:zephyr
    libraries:
default_profile: default
```

## Bridge API ✅
MCU (`#include "Arduino_RouterBridge.h"`):
- `Bridge.begin();` in `setup()`.
- `Bridge.notify("name", args...)`: fire-and-forget call to Python. **This is what we use for button → Python.**
- `Bridge.call("name", args...).result(var)`: blocking call to Python (returns bool ok).
- `Bridge.provide("name", fn)`: exposes fn to Python. It runs in a high-priority RPC thread. **Do NOT use `Monitor.print` or `Bridge.call` inside it (deadlock).**
- `Bridge.provide_safe("name", fn)`: same, but runs inside `loop()` context, so it is safe for `digitalWrite`. **This is what we use for Python → vibration motor.**

Python (`from arduino.app_utils import *`):
- `Bridge.provide("name", fn)` receives MCU notify/call.
- `Bridge.notify("name", *args)` / `Bridge.call("name", *args)` call the MCU.
- `App.run()` or `App.run(user_loop=fn)` keeps the app alive (mandatory).
- The max message size is 256 bytes, and the transport is `/dev/ttyHS1` ↔ `Serial1`. **Never open `Serial1` in a sketch.**

## Debug printing ✅
- MCU: `Monitor.begin(); Monitor.println(...)` appears in App Lab Console → **Serial Monitor** tab. (`Serial` is not the App Lab monitor on UNO Q.)
- Python: `print()` appears in App Lab Console → **Python** tab. CLI: `arduino-app-cli app logs <app_path> --follow`.

## Linux side can make HTTP requests ✅
The official `air-quality-monitoring` example uses `import requests` in `python/main.py`. Our app uses only
**stdlib `urllib.request`**, so it needs no `requirements.txt` and no internet to install packages.

## Wi-Fi / USB vs Network mode ✅
- First-time setup **must be over USB-C**. The App Lab wizard sets the board name, the Wi-Fi network (WPA/WPA2 Personal; captive portals are NOT supported) and the Linux password for user `arduino`.
- **Network Mode** (Wi-Fi icon next to the board in App Lab) becomes available once Wi-Fi is configured. It uses mDNS (UDP 5353) for discovery and SSH (TCP 22) for deploy. On Windows, allow `mdns-discovery.exe` through the firewall when prompted.
- SSH: `ssh arduino@<board-name>.local` (Linux password from the wizard).
- **Run at Startup**: open App → ▼ next to the app name → enable *Run at Startup*. Only one app can do this at a time. CLI: `arduino-app-cli properties set default <app_path>`. This is how the app runs from a power bank with no laptop.

## Unconfirmed assumptions ⚠️ (and where to fix them)
| Assumption | Where isolated |
|---|---|
| A Python callback registered with `Bridge.provide` may block for a while. We avoid relying on this: the HTTP work runs in a worker thread. | `uno_q_app/python/main.py` → `on_button()` |
| `Bridge.notify` from a Python *worker thread* (not the callback thread) is safe. | `uno_q_app/python/main.py` → `haptic()` (single function) |
| The buzzer was replaced by a vibration motor **module** on D3 (driver on board). Plain `digitalWrite` HIGH/LOW, so no `tone()` is needed. | `hapticStart()` / `hapticUpdate()` in both sketches |
| `analogRead(A0)` returns 10-bit (0–1023) by default on the UNO Q core. The threshold is a constant, so tune it from the printed values. | `CLAP_THRESHOLD` in both sketches |
| `INPUT_PULLUP` / `INPUT_PULLDOWN` are available on Zephyr core pins. If `INPUT_PULLDOWN` does not compile, use `INPUT` (Grove button modules drive the line themselves). | `configureButtonPin()` in both sketches |
| Whether `Monitor.println` output appears without App Lab attached. Not needed: the self-test is designed for App Lab's Serial Monitor tab. | n/a |
| Grove Base Shield V2 fits the UNO Q headers and works at 3.3V (UNO form factor, so expected). | wiring tables in README |

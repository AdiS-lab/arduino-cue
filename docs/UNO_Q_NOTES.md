# Arduino UNO Q — verified notes

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
- `Bridge.provide_safe("name", fn)`: same, but runs inside `loop()` context, so it is safe for `digitalWrite`. **This is what we use for Python → buzzer.**

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
| `Bridge.notify` from a Python *worker thread* (not the callback thread) is safe. | `uno_q_app/python/main.py` → `beep()` (single function) |
| `tone()` exists on the Zephyr core. **Avoided**: the buzzer is driven by a bit-banged square wave (works for passive AND active buzzers). | `buzzerOn/Off` + `beepMs()` in both sketches |
| `analogRead(A0)` returns 10-bit (0–1023) by default on the UNO Q core. The threshold is a constant, so tune it from the printed values. | `CLAP_THRESHOLD` in both sketches |
| `INPUT_PULLUP` / `INPUT_PULLDOWN` are available on Zephyr core pins. If `INPUT_PULLDOWN` does not compile, use `INPUT` (Grove button modules drive the line themselves). | `configureButtonPin()` in both sketches |
| Whether `Monitor.println` output appears without App Lab attached. Not needed: the self-test is designed for App Lab's Serial Monitor tab. | n/a |
| Grove Base Shield V2 fits the UNO Q headers and works at 3.3V (UNO form factor, so expected). | wiring tables in README |

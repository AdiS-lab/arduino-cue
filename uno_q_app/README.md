# arduino-cue UNO Q ring app: BACKUP wearable (UNTESTED ON HARDWARE)

Wireless ring button. Button D2 → MCU → Bridge → Linux Python → `POST http://LAPTOP_IP:PORT/trigger` → vibration pulse. Camera = USB (Inland/C270) on the laptop, `CAMERA_SOURCE=usb`.

## Configure
Edit the top of `python/main.py`:
```python
LAPTOP_IP = "172.20.10.2"     # the laptop's hotspot IP (server.py prints it at startup)
PORT = 8000
```
Button wiring and the optional clap trigger are set at the top of `sketch/sketch.ino` (`BUTTON_WIRING`, `CLAP_ENABLED`).

## Vibration meanings (motor module on D3)
| Vibration | Meaning |
|---|---|
| 1 pulse at power-on | MCU booted (no network needed) |
| 3 pulses, repeating every ~5 s | laptop `/health` not reachable (wrong IP, server not running, firewall, different Wi-Fi) |
| 1 × 150 ms after a press | `ok`: a word was detected |
| 2 × 100 ms | `none`: nothing recognised |
| nothing | `busy`: a capture was already running |
| 1 × 600 ms | `error`, timeout > 5 s, or laptop unreachable. Python logs `BUTTON OK, LAPTOP UNREACHABLE`. The MCU also plays this on its own if Linux never answers within 6.5 s. |

## Run without the laptop cable (power bank + hotspot)
1. First time only: connect over USB-C, then use the App Lab wizard to join the **phone hotspot** (WPA2; captive portals are not supported).
2. Load this App, then use **▼ next to the app name → Run at Startup**.
3. Unplug from the laptop and power it from a USB-C power bank. The board boots and starts the App by itself.
4. Some power banks switch off at low current draw. If the board dies after ~30 s, use a bank with an "always on" or low-current mode, or keep a phone charging from the same bank.
5. Debug wirelessly: App Lab **Network Mode** (Wi-Fi icon), or `ssh arduino@<board-name>.local` and
   `arduino-app-cli app logs <app_path> --follow`.
6. Check reachability from the UNO Q shell: `curl http://LAPTOP_IP:8000/health`

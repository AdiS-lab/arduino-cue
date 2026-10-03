# arduino-cue ESP32-CAM ring firmware (UNTESTED ON HARDWARE; compiles for esp32 core 3.3.1)

Based on the official [CameraWebServer example](https://github.com/espressif/arduino-esp32/tree/master/libraries/ESP32/examples/Camera/CameraWebServer)
(Apache-2.0). `app_httpd.cpp`, `camera_index.h`, `camera_pins.h` and `partitions.csv` are vendored unchanged except for 2 lines marked
`arduino-cue` in `app_httpd.cpp`. `board_config.h` selects `CAMERA_MODEL_AI_THINKER`.

1. `copy secrets.example.h secrets.h` and fill in the hotspot (2.4 GHz) and LAPTOP_IP.
2. Arduino IDE 2: board **AI Thinker ESP32-CAM**, then Upload (on the ESP32-CAM-MB). Open Serial Monitor 115200 and note the IP.

| Endpoint | |
|---|---|
| `:81/stream` | MJPEG (laptop preview) |
| `/capture` | one JPEG (laptop burst, `BURST_MODE=snapshot`) |
| `/control?var=&val=` / `/status` | camera settings (laptop forwards framesize, quality, brightness, contrast, hmirror, vflip) |
| `/haptic?pattern=ok\|none\|error\|boot_fail` | vibrate (added) |
| `/cue` | ring status JSON (added) |

Button GPIO13 → `POST /trigger {"source":"ring","device":"esp32cam","ts":0}` (`ts:0` means the laptop stamps its own time; no NTP needed).
The response status picks the vibration on GPIO14. HTTP runs in its own FreeRTOS task with a 5 s timeout, haptics are millis-based,
debounce is 50 ms and cooldown 1500 ms.

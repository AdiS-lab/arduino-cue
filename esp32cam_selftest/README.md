# ESP32-CAM hardware self-test (UNTESTED ON HARDWARE)

No Wi-Fi, no camera, no laptop needed. Flash the board on the ESP32-CAM-MB: Arduino IDE 2, board **AI Thinker ESP32-CAM**.
Then open Serial Monitor at **115200**.

1. Boot gives **1 pulse** (motor OK), and the wiring summary prints. It repeats every 15 s.
2. Each press gives a **short pulse** and prints `BUTTON PRESSED #n`. Raw pin changes print as `raw GPIO13 -> 0/1`.
3. Bare 2-leg button wired GPIO13↔GND? Set `BUTTON_WIRING = 1`.

# arduino-cue hardware self-test (UNTESTED ON HARDWARE)

Use this App to check the button, buzzer and sound sensor. It needs no laptop server and no Wi-Fi.

1. Wire it: Button → D2, Buzzer → D3, optional Sound sensor → A0, all on **3.3V**.
2. Run this App from App Lab and open Console → **Serial Monitor**.
3. Boot: **1 short beep** means the buzzer is OK. The wiring summary prints and repeats every 15 s.
4. Press the button: you should get a beep, the built-in LED flashes, and `BUTTON PRESSED #n` prints.
5. Bare 2-leg button wired D2↔GND? Set `BUTTON_WIRING = 1` at the top of `sketch/sketch.ino`.
6. Sound sensor? Set `SOUND_SENSOR_CONNECTED = true`. The value prints every 200 ms. A clap gives a double beep and `CLAP <v>`.

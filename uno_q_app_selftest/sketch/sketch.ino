// arduino-cue HARDWARE SELF-TEST. Runs entirely on the UNO Q, with no laptop and no network.
// UNTESTED ON HARDWARE. Structure follows the official App Lab examples (see docs/UNO_Q_NOTES.md).
//
// What it does:
//   boot     -> 1 short beep + wiring summary in App Lab "Serial Monitor" tab (repeated every 15 s)
//   button   -> every debounced press: short beep + built-in LED flash + "BUTTON PRESSED #n"
//               every RAW pin change is printed too, so wrong polarity / floating pin is obvious
//   sound A0 -> (set SOUND_SENSOR_CONNECTED true) value printed every 200 ms, loud -> double beep + "CLAP <v>"

#include "Arduino_RouterBridge.h"

// ======================= EDIT THESE IF NEEDED =======================
const int BUTTON_PIN = 2;   // D2
const int BUZZER_PIN = 3;   // D3
const int SOUND_PIN  = A0;  // A0

// BUTTON_WIRING:
//   0 = Grove / 3-pin button module (SIG goes HIGH when pressed)   -> pin INPUT, active HIGH
//   1 = bare 2-leg pushbutton between D2 and GND                   -> pin INPUT_PULLUP, active LOW
const int BUTTON_WIRING = 0;

const bool SOUND_SENSOR_CONNECTED = false;  // true = print A0 every 200 ms and detect claps
const int  CLAP_THRESHOLD = 600;            // 0..1023 (assumed 10-bit); tune from printed values
const unsigned long DEBOUNCE_MS = 50;
// ====================================================================

bool activeHigh() { return BUTTON_WIRING == 0; }

// Single place for pin mode. If INPUT_PULLDOWN fails to compile on this core, change it to INPUT.
void configureButtonPin() {
  if (BUTTON_WIRING == 1) pinMode(BUTTON_PIN, INPUT_PULLUP);
  else pinMode(BUTTON_PIN, INPUT_PULLDOWN);  // internal pull-down keeps an unplugged pin from floating
}

// Buzzer: bit-banged ~2 kHz square wave. Works for PASSIVE and ACTIVE buzzers and does not need tone().
void buzzerOn()  { digitalWrite(BUZZER_PIN, HIGH); }
void buzzerOff() { digitalWrite(BUZZER_PIN, LOW); }
void beepMs(unsigned long ms) {
  unsigned long start = millis();
  while (millis() - start < ms) {
    buzzerOn();  delayMicroseconds(250);
    buzzerOff(); delayMicroseconds(250);
  }
  buzzerOff();
}
void beeps(int n, unsigned long ms) {
  for (int i = 0; i < n; i++) { beepMs(ms); if (i < n - 1) delay(120); }
}

void led(bool on) { digitalWrite(LED_BUILTIN, on ? LOW : HIGH); }  // UNO Q built-in LED is active LOW

void printWiring() {
  Monitor.println("==== arduino-cue SELF-TEST (UNTESTED ON HARDWARE) ====");
  Monitor.println("Button  -> D2   Buzzer -> D3   Sound sensor (optional) -> A0");
  Monitor.println("Power modules from 3.3V (Grove Base Shield switch at 3V3), GND to GND.");
  if (BUTTON_WIRING == 0) Monitor.println("BUTTON_WIRING=0 (module): expect raw 0 idle, 1 pressed");
  else Monitor.println("BUTTON_WIRING=1 (bare button to GND, pull-up): expect raw 1 idle, 0 pressed");
  Monitor.print("Sound sensor: "); Monitor.println(SOUND_SENSOR_CONNECTED ? "ON (A0 every 200ms)" : "OFF");
  Monitor.println("Press the button: you should hear a beep and see BUTTON PRESSED #n");
}

int rawState;               // last raw reading
int stableState;            // debounced reading
unsigned long lastRawChange = 0;
unsigned long pressCount = 0;
unsigned long rawChangesThisSecond = 0, secondStart = 0;
unsigned long lastSoundPrint = 0, lastClap = 0, lastWiringPrint = 0;

void setup() {
  pinMode(BUZZER_PIN, OUTPUT);
  buzzerOff();
  pinMode(LED_BUILTIN, OUTPUT);
  led(false);
  configureButtonPin();

  Bridge.begin();
  Monitor.begin();
  delay(300);

  beepMs(100);  // BOOT BEEP: if you hear this, the buzzer wiring is OK
  printWiring();

  rawState = stableState = digitalRead(BUTTON_PIN);
  Monitor.print("Initial raw D2 = "); Monitor.println(rawState);
  if (rawState == (activeHigh() ? HIGH : LOW))
    Monitor.println("WARNING: button reads PRESSED at boot -> wrong BUTTON_WIRING or stuck button");
  lastWiringPrint = secondStart = millis();
}

void loop() {
  unsigned long now = millis();

  // ---- button: raw changes + debounce ----
  int r = digitalRead(BUTTON_PIN);
  if (r != rawState) {
    rawState = r;
    lastRawChange = now;
    rawChangesThisSecond++;
    Monitor.print("raw D2 -> "); Monitor.println(r);
  }
  if (r != stableState && now - lastRawChange >= DEBOUNCE_MS) {
    stableState = r;
    bool pressed = (stableState == HIGH) == activeHigh();
    if (pressed) {
      pressCount++;
      Monitor.print("BUTTON PRESSED #"); Monitor.println(pressCount);
      led(true); beepMs(80); led(false);
    } else {
      Monitor.println("button released");
    }
  }
  if (now - secondStart >= 1000) {
    if (rawChangesThisSecond > 20)
      Monitor.println("WARNING: D2 is chattering (>20 changes/s) -> floating pin or loose wire; check GND/3V3/SIG");
    rawChangesThisSecond = 0;
    secondStart = now;
  }

  // ---- sound sensor ----
  if (SOUND_SENSOR_CONNECTED && now - lastSoundPrint >= 200) {
    lastSoundPrint = now;
    int v = analogRead(SOUND_PIN);
    Monitor.print("A0 = "); Monitor.println(v);
    if (v > CLAP_THRESHOLD && now - lastClap > 1000) {
      lastClap = now;
      Monitor.print("CLAP "); Monitor.println(v);
      beeps(2, 80);
    }
  }

  // reprint the wiring summary in case the monitor was opened late
  if (now - lastWiringPrint >= 15000) {
    lastWiringPrint = now;
    printWiring();
    Monitor.print("presses so far: "); Monitor.println(pressCount);
  }
}

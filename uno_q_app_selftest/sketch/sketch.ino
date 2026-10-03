// arduino-cue HARDWARE SELF-TEST. Runs entirely on the UNO Q, with no laptop and no network.
// UNTESTED ON HARDWARE. Structure follows the official App Lab examples (see docs/HARDWARE_NOTES.md).
//
// What it does:
//   boot     -> 1 vibration pulse + wiring summary in App Lab "Serial Monitor" tab (repeated every 15 s)
//   button   -> every debounced press: short pulse + built-in LED flash + "BUTTON PRESSED #n"
//               every RAW pin change is printed too, so wrong polarity / floating pin is obvious
//   sound A0 -> (set SOUND_SENSOR_CONNECTED true) value printed every 200 ms, loud -> double pulse + "CLAP <v>"

#include "Arduino_RouterBridge.h"

// ======================= EDIT THESE IF NEEDED =======================
const int BUTTON_PIN = 2;   // D2
const int MOTOR_PIN  = 3;   // D3 -> vibration motor module
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

// Vibration motor MODULE on D3: HIGH = on. Non-blocking: a list of on/off steps driven from loop().
unsigned long hapSteps[8]; int hapCount = 0, hapIndex = 0; unsigned long hapStepStart = 0; bool hapActive = false;
void hapticStart(int pulses, unsigned long onMs, unsigned long gapMs = 120) {
  hapCount = 0;
  for (int i = 0; i < pulses && hapCount < 7; i++) { hapSteps[hapCount++] = onMs; if (i < pulses - 1) hapSteps[hapCount++] = gapMs; }
  hapIndex = 0; hapStepStart = millis(); hapActive = hapCount > 0;
  digitalWrite(MOTOR_PIN, hapActive ? HIGH : LOW);
}
void hapticUpdate() {
  if (!hapActive) return;
  if (millis() - hapStepStart >= hapSteps[hapIndex]) {
    hapIndex++; hapStepStart = millis();
    if (hapIndex >= hapCount) { hapActive = false; digitalWrite(MOTOR_PIN, LOW); return; }
    digitalWrite(MOTOR_PIN, (hapIndex % 2 == 0) ? HIGH : LOW);
  }
}

void led(bool on) { digitalWrite(LED_BUILTIN, on ? LOW : HIGH); }  // UNO Q built-in LED is active LOW

void printWiring() {
  Monitor.println("==== arduino-cue SELF-TEST (UNTESTED ON HARDWARE) ====");
  Monitor.println("Button  -> D2   Vibration motor module -> D3   Sound sensor (optional) -> A0");
  Monitor.println("Power modules from 3.3V (Grove Base Shield switch at 3V3), GND to GND.");
  if (BUTTON_WIRING == 0) Monitor.println("BUTTON_WIRING=0 (module): expect raw 0 idle, 1 pressed");
  else Monitor.println("BUTTON_WIRING=1 (bare button to GND, pull-up): expect raw 1 idle, 0 pressed");
  Monitor.print("Sound sensor: "); Monitor.println(SOUND_SENSOR_CONNECTED ? "ON (A0 every 200ms)" : "OFF");
  Monitor.println("Press the button: you should feel a pulse and see BUTTON PRESSED #n");
}

int rawState;               // last raw reading
int stableState;            // debounced reading
unsigned long lastRawChange = 0;
unsigned long pressCount = 0;
unsigned long rawChangesThisSecond = 0, secondStart = 0;
unsigned long lastSoundPrint = 0, lastClap = 0, lastWiringPrint = 0;

void setup() {
  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);
  pinMode(LED_BUILTIN, OUTPUT);
  led(false);
  configureButtonPin();

  Bridge.begin();
  Monitor.begin();
  delay(300);

  hapticStart(1, 150);  // BOOT PULSE: if you feel this, the motor wiring is OK
  printWiring();

  rawState = stableState = digitalRead(BUTTON_PIN);
  Monitor.print("Initial raw D2 = "); Monitor.println(rawState);
  if (rawState == (activeHigh() ? HIGH : LOW))
    Monitor.println("WARNING: button reads PRESSED at boot -> wrong BUTTON_WIRING or stuck button");
  lastWiringPrint = secondStart = millis();
}

void loop() {
  unsigned long now = millis();
  hapticUpdate();
  if (!hapActive) led(false);

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
      led(true); hapticStart(1, 150);
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
      hapticStart(2, 100);
    }
  }

  // reprint the wiring summary in case the monitor was opened late
  if (now - lastWiringPrint >= 15000) {
    lastWiringPrint = now;
    printWiring();
    Monitor.print("presses so far: "); Monitor.println(pressCount);
  }
}

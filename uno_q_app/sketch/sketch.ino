// arduino-cue main app (MCU side). UNTESTED ON HARDWARE.
// Button (D2) -> Bridge.notify("button_pressed", n) -> Python -> laptop.
// Python replies with Bridge.notify("play", pattern) -> vibration motor (D3).
// If Python never replies within REPLY_TIMEOUT_MS, the MCU plays 1 long pulse by itself,
// so a press always produces feedback.

#include "Arduino_RouterBridge.h"

// ======================= EDIT THESE IF NEEDED =======================
const int BUTTON_PIN = 2;
const int MOTOR_PIN  = 3;   // vibration motor module
const int SOUND_PIN  = A0;
const int BUTTON_WIRING = 0;        // 0 = Grove/module (active HIGH), 1 = bare button to GND (pull-up, active LOW)
const bool CLAP_ENABLED = false;    // optional sound-sensor trigger on A0
const int  CLAP_THRESHOLD = 600;
const unsigned long DEBOUNCE_MS = 50;
const unsigned long COOLDOWN_MS = 1500;
const unsigned long REPLY_TIMEOUT_MS = 6500;   // Python HTTP timeout is 5 s
// ====================================================================

void configureButtonPin() {
  if (BUTTON_WIRING == 1) pinMode(BUTTON_PIN, INPUT_PULLUP);
  else pinMode(BUTTON_PIN, INPUT_PULLDOWN);   // if this fails to compile, use INPUT
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

// ---- Python -> MCU: pattern request. provide_safe runs this in loop() context; we only store it.
volatile int pendingPattern = -1;    // -1 none, 0 silent, 1 ok, 2 none, 3 error, 4 boot_fail
void play(String pattern) {
  if (pattern == "ok") pendingPattern = 1;
  else if (pattern == "none") pendingPattern = 2;
  else if (pattern == "error") pendingPattern = 3;
  else if (pattern == "boot_fail") pendingPattern = 4;
  else pendingPattern = 0;           // "silent" (busy) or unknown
}

void runPattern(int p) {
  switch (p) {
    case 1: hapticStart(1, 150); break;  // ok: 1 x 150 ms
    case 2: hapticStart(2, 100); break;  // none: 2 x 100 ms
    case 3: hapticStart(1, 600); break;  // error / timeout / unreachable: 1 x 600 ms
    case 4: hapticStart(3, 100); break;  // laptop /health unreachable at boot: 3 pulses
    default: break;                      // busy: nothing
  }
}

int rawState, stableState;
unsigned long lastRawChange = 0, lastTrigger = 0, waitingSince = 0, lastClap = 0;
unsigned long pressCount = 0;
bool waitingReply = false;

bool isPressed(int level) { return (level == HIGH) == (BUTTON_WIRING == 0); }

void setup() {
  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);
  configureButtonPin();

  Bridge.begin();
  Monitor.begin();
  Bridge.provide_safe("play", play);

  hapticStart(1, 150);   // boot: 1 pulse (no network needed)
  rawState = stableState = digitalRead(BUTTON_PIN);
  Monitor.println("arduino-cue main app (MCU). Button D2, vibration motor D3. UNTESTED ON HARDWARE.");
}

void sendTrigger(const char* kind, unsigned long value) {
  unsigned long now = millis();
  if (now - lastTrigger < COOLDOWN_MS) {
    Monitor.println("press ignored (cooldown)");
    return;
  }
  lastTrigger = now;
  waitingReply = true;
  waitingSince = now;
  pendingPattern = -1;
  if (kind[0] == 'b') {
    Monitor.print("BUTTON PRESSED #"); Monitor.println(value);
    Bridge.notify("button_pressed", (int)value);
  } else {
    Monitor.print("CLAP "); Monitor.println(value);
    Bridge.notify("clap", (int)value);
  }
}

void loop() {
  unsigned long now = millis();
  hapticUpdate();

  int r = digitalRead(BUTTON_PIN);
  if (r != rawState) { rawState = r; lastRawChange = now; }
  if (r != stableState && now - lastRawChange >= DEBOUNCE_MS) {
    stableState = r;
    if (isPressed(stableState)) sendTrigger("button", ++pressCount);
  }

  if (CLAP_ENABLED) {
    int v = analogRead(SOUND_PIN);
    if (v > CLAP_THRESHOLD && now - lastClap > COOLDOWN_MS) { lastClap = now; sendTrigger("clap", v); }
  }

  int p = pendingPattern;
  if (p >= 0) {
    pendingPattern = -1;
    waitingReply = false;
    runPattern(p);
  } else if (waitingReply && now - waitingSince > REPLY_TIMEOUT_MS) {
    waitingReply = false;
    Monitor.println("BUTTON OK, NO REPLY FROM LINUX/LAPTOP -> long pulse");
    runPattern(3);
  }
}

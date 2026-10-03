// arduino-cue ESP32-CAM HARDWARE SELF-TEST. No Wi-Fi, no camera, no laptop.
// UNTESTED ON HARDWARE.
// Board: "AI Thinker ESP32-CAM" (Arduino IDE 2, core "esp32" by Espressif). Serial Monitor at 115200.
//
//   boot   -> 1 haptic pulse + wiring summary (repeated every 15 s)
//   button -> every debounced press: short pulse + "BUTTON PRESSED #n"; every raw pin change is printed

// ======================= EDIT THESE IF NEEDED =======================
const int BUTTON_PIN = 13;   // GPIO13 (free on AI Thinker when the SD card is unused)
const int MOTOR_PIN  = 14;   // GPIO14 -> vibration motor MODULE signal pin
const int FLASH_LED_PIN = 4; // GPIO4 flash LED: forced OFF here
// BUTTON_WIRING:
//   0 = Grove / 3-pin button module (SIG HIGH when pressed)  -> INPUT_PULLDOWN, active HIGH
//   1 = bare 2-leg pushbutton between GPIO13 and GND          -> INPUT_PULLUP,   active LOW
const int BUTTON_WIRING = 0;
const unsigned long DEBOUNCE_MS = 50;
// ====================================================================

// ---- non-blocking haptics: a queue of on/off steps driven from loop() ----
unsigned long hapSteps[8]; int hapCount = 0, hapIndex = 0; unsigned long hapStepStart = 0; bool hapActive = false;
void hapticStart(int pulses, unsigned long onMs, unsigned long gapMs = 120) {
  hapCount = 0;
  for (int i = 0; i < pulses && hapCount < 7; i++) { hapSteps[hapCount++] = onMs; if (i < pulses - 1) hapSteps[hapCount++] = gapMs; }
  hapIndex = 0; hapStepStart = millis(); hapActive = hapCount > 0;
  digitalWrite(MOTOR_PIN, hapActive ? HIGH : LOW);   // even steps = motor ON, odd steps = gap
}
void hapticUpdate() {
  if (!hapActive) return;
  if (millis() - hapStepStart >= hapSteps[hapIndex]) {
    hapIndex++; hapStepStart = millis();
    if (hapIndex >= hapCount) { hapActive = false; digitalWrite(MOTOR_PIN, LOW); return; }
    digitalWrite(MOTOR_PIN, (hapIndex % 2 == 0) ? HIGH : LOW);
  }
}

bool activeHigh() { return BUTTON_WIRING == 0; }

void printWiring() {
  Serial.println("==== arduino-cue ESP32-CAM SELF-TEST (UNTESTED ON HARDWARE) ====");
  Serial.println("Button: SIG(yellow)->GPIO13  VCC(red)->3V3  GND(black)->GND  (white unused)");
  Serial.println("Motor : SIG(yellow)->GPIO14  VCC(red)->VCC pin  GND(black)->GND  (use a motor MODULE, not a bare motor)");
  Serial.println("Nothing on GPIO0 / GPIO12. Flash LED GPIO4 is OFF.");
  if (BUTTON_WIRING == 0) Serial.println("BUTTON_WIRING=0 (module): expect raw 0 idle, 1 pressed");
  else Serial.println("BUTTON_WIRING=1 (bare button to GND): expect raw 1 idle, 0 pressed");
  Serial.println("Press the button: you should feel a pulse and see BUTTON PRESSED #n");
}

int rawState, stableState;
unsigned long lastRawChange = 0, pressCount = 0, rawChanges = 0, secondStart = 0, lastWiringPrint = 0;

void setup() {
  pinMode(FLASH_LED_PIN, OUTPUT); digitalWrite(FLASH_LED_PIN, LOW);
  pinMode(MOTOR_PIN, OUTPUT);     digitalWrite(MOTOR_PIN, LOW);
  pinMode(BUTTON_PIN, BUTTON_WIRING == 1 ? INPUT_PULLUP : INPUT_PULLDOWN);
  Serial.begin(115200);
  delay(300);
  printWiring();
  hapticStart(1, 150);   // BOOT PULSE: if you feel this, the motor wiring is OK
  rawState = stableState = digitalRead(BUTTON_PIN);
  Serial.printf("Initial raw GPIO13 = %d\n", rawState);
  if (rawState == (activeHigh() ? HIGH : LOW))
    Serial.println("WARNING: button reads PRESSED at boot -> wrong BUTTON_WIRING or stuck button");
  lastWiringPrint = secondStart = millis();
}

void loop() {
  unsigned long now = millis();
  hapticUpdate();

  int r = digitalRead(BUTTON_PIN);
  if (r != rawState) { rawState = r; lastRawChange = now; rawChanges++; Serial.printf("raw GPIO13 -> %d\n", r); }
  if (r != stableState && now - lastRawChange >= DEBOUNCE_MS) {
    stableState = r;
    if ((stableState == HIGH) == activeHigh()) {
      pressCount++;
      Serial.printf("BUTTON PRESSED #%lu\n", pressCount);
      hapticStart(1, 150);
    } else {
      Serial.println("button released");
    }
  }
  if (now - secondStart >= 1000) {
    if (rawChanges > 20) Serial.println("WARNING: GPIO13 chattering (>20 changes/s) -> floating pin / loose wire / wrong BUTTON_WIRING");
    rawChanges = 0; secondStart = now;
  }
  if (now - lastWiringPrint >= 15000) {
    lastWiringPrint = now; printWiring(); Serial.printf("presses so far: %lu\n", pressCount);
  }
}

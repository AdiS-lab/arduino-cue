# arduino-cue self-test: all logic is in sketch/sketch.ino (runs on the MCU).
# UNTESTED ON HARDWARE. This file only keeps the App alive, as in the official examples.
from arduino.app_utils import App

print("arduino-cue self-test running. Open the 'Serial Monitor' tab and press the button on D2.")

App.run()

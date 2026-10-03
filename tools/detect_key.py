"""Print the name of every key pressed (incl. Bluetooth ring remotes, which act as keyboards).
Use the printed name in BLE_KEYS for laptop\\ble_remote.py.

    python tools\\detect_key.py      (Ctrl+C to quit)
"""
import keyboard


def show(e):
    if e.event_type == "down":
        print(f"key: {e.name!r}   scan_code: {e.scan_code}")


if __name__ == "__main__":
    print("Press buttons on the ring remote...")
    keyboard.hook(show)
    try:
        keyboard.wait()
    except KeyboardInterrupt:
        pass

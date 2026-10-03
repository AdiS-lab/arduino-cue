"""Simulate the wireless UNO Q button on the laptop. It runs the REAL uno_q_app/python/main.py logic
with a fake Bridge that prints the beeps instead of playing them.

    python tools\\mock_unoq.py                      # health check, then press Enter = button press
    python tools\\mock_unoq.py --presses 3          # 3 presses, 2 s apart, then exit
    python tools\\mock_unoq.py --ip 10.0.0.5 --port 8000
"""
import argparse
import importlib.util
import time
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent / "uno_q_app" / "python" / "main.py"
BEEPS = {"ok": "beep (1 short)", "none": "beep beep (2 short)", "error": "BEEEEEP (1 long)",
         "boot_fail": "beep beep beep (3 short)", "silent": "(no beep: busy)"}


class FakeBridge:
    def __init__(self):
        self.played = []

    def notify(self, name, *args):
        if name == "play":
            self.played.append(args[0])
            print(f"   [MCU buzzer] {BEEPS.get(args[0], args[0])}")

    def provide(self, name, fn):
        pass


def load_unoq(ip=None, port=None):
    spec = importlib.util.spec_from_file_location("unoq_main", MAIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # ON_BOARD is False off-board, so App.run() is not called
    mod.Bridge = FakeBridge()
    if ip:
        mod.LAPTOP_IP = ip
    if port:
        mod.PORT = port
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--presses", type=int, default=0, help="auto-press N times then exit")
    ap.add_argument("--gap", type=float, default=2.0)
    a = ap.parse_args()
    u = load_unoq(a.ip, a.port)
    print(f"Mock UNO Q -> {u.base_url()}")
    print("[MCU buzzer] beep (boot)")
    u.health_check_loop(max_tries=1)
    n = 0
    if a.presses:
        for _ in range(a.presses):
            n += 1
            print(f"BUTTON PRESSED #{n}")
            u.handle_trigger("button", n)
            time.sleep(a.gap)
        return
    print("Press Enter to simulate the button (Ctrl+C to quit).")
    while True:
        input()
        n += 1
        print(f"BUTTON PRESSED #{n}")
        u.handle_trigger("button", n)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

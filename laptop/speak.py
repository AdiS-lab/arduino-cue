"""Offline text-to-speech on a background thread (pyttsx3 uses SAPI5 on Windows).

say(text) returns immediately. If TTS is unavailable it logs and carries on.
"""
import queue
import threading

import config

_q: "queue.Queue[str]" = queue.Queue()
_thread = None
available = None  # None = unknown, True/False after first attempt


def _worker():
    global available
    while True:
        text = _q.get()
        try:
            import pyttsx3
            # A fresh engine per utterance avoids the known pyttsx3 "second runAndWait hangs" issue on Windows.
            engine = pyttsx3.init()
            engine.setProperty("rate", config.TTS_RATE)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
            available = True
        except Exception as e:
            if available is not False:
                print(f"[speak] TTS unavailable ({e}); continuing without audio")
            available = False


def say(text: str) -> bool:
    global _thread
    text = (text or "").strip()
    if not text or not config.TTS_ENABLED:
        return False
    if _thread is None:
        _thread = threading.Thread(target=_worker, daemon=True, name="tts")
        _thread.start()
    _q.put(text)
    print(f"[speak] {text}")
    return True

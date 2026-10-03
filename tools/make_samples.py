"""Generate simple synthetic object images into samples/ (own work, CC0 / public domain).

The mock camera cycles these, and mock CV can read the label from the filename.
You can drop real photos into samples/ too. Name them <label>.jpg, e.g. "apple.jpg" or "cup_2.jpg".
"""
from pathlib import Path
import cv2
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "samples"
W, H = 640, 480


def canvas(bg):
    img = np.full((H, W, 3), bg, np.uint8)
    noise = np.random.default_rng(0).integers(0, 12, (H, W, 3), dtype=np.uint8)
    return cv2.add(img, noise)


def apple():
    img = canvas((215, 230, 240))
    cv2.circle(img, (320, 260), 120, (40, 40, 200), -1)
    cv2.circle(img, (280, 220), 30, (120, 120, 255), -1)
    cv2.line(img, (320, 145), (335, 95), (30, 60, 90), 10)
    cv2.ellipse(img, (365, 115), (40, 18), -20, 0, 360, (40, 160, 40), -1)
    return img


def ball():
    img = canvas((200, 220, 200))
    cv2.circle(img, (320, 240), 140, (0, 200, 255), -1)
    cv2.ellipse(img, (320, 240), (140, 50), 0, 0, 360, (255, 255, 255), 8)
    cv2.ellipse(img, (320, 240), (50, 140), 0, 0, 360, (255, 255, 255), 8)
    return img


def cup():
    img = canvas((235, 225, 210))
    pts = np.array([[220, 140], [420, 140], [390, 380], [250, 380]], np.int32)
    cv2.fillPoly(img, [pts], (180, 90, 30))
    cv2.ellipse(img, (440, 250), (60, 70), 0, -90, 90, (180, 90, 30), 22)
    cv2.ellipse(img, (320, 140), (100, 20), 0, 0, 360, (60, 30, 10), -1)
    return img


def banana():
    img = canvas((190, 200, 225))
    cv2.ellipse(img, (320, 180), (220, 140), 0, 20, 160, (0, 220, 250), 55)
    cv2.circle(img, (125, 235), 10, (20, 60, 80), -1)
    return img


def book():
    img = canvas((210, 210, 210))
    cv2.rectangle(img, (190, 100), (450, 400), (60, 60, 160), -1)
    cv2.rectangle(img, (190, 100), (215, 400), (30, 30, 100), -1)
    cv2.rectangle(img, (250, 160), (420, 200), (220, 220, 240), -1)
    return img


def bottle():
    img = canvas((225, 215, 200))
    cv2.rectangle(img, (260, 180), (380, 420), (200, 150, 60), -1)
    cv2.rectangle(img, (295, 110), (345, 180), (200, 150, 60), -1)
    cv2.rectangle(img, (290, 85), (350, 110), (40, 40, 40), -1)
    cv2.rectangle(img, (260, 260), (380, 320), (255, 255, 255), -1)
    return img


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for fn in (apple, ball, cup, banana, book, bottle):
        cv2.imwrite(str(OUT / f"{fn.__name__}.jpg"), fn())
        print("wrote", OUT / f"{fn.__name__}.jpg")

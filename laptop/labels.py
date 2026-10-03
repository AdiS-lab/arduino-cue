"""Optional display mapping: detector label -> word tile text + emoji. Unknown labels pass through."""

LABELS = {
    "apple": ("apple", "🍎"),
    "banana": ("banana", "🍌"),
    "ball": ("ball", "⚽"),
    "sports ball": ("ball", "⚽"),
    "cup": ("cup", "🥤"),
    "bottle": ("water", "💧"),
    "book": ("book", "📖"),
    "cell phone": ("phone", "📱"),
    "teddy bear": ("teddy", "🧸"),
    "dog": ("dog", "🐶"),
    "cat": ("cat", "🐱"),
    "chair": ("chair", "🪑"),
    "toothbrush": ("toothbrush", "🪥"),
    "spoon": ("spoon", "🥄"),
    "car": ("car", "🚗"),
}


def display(label: str) -> dict:
    key = (label or "").strip().lower()
    word, emoji = LABELS.get(key, (key, ""))
    return {"word": word, "emoji": emoji}

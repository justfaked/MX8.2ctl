"""Key layout of the keyboard: which LED slot each key uses and where it sits.

The layout files were extracted from the Cherry Utility 3.12 layout data
(MX 8.2 XAGA TKL). Key positions are normalized to 0..1 of the keyboard
picture; "index" is the key's slot in the custom color table.
"""

import json
import statistics
from dataclasses import dataclass
from importlib import resources

# Short labels for keys whose German label isn't printed in the layout file.
SHORT_LABELS = {
    "Escape": "Esc",
    "Print": "Druck",
    "ScrollLock": "Rollen",
    "Pause": "Pause",
    "Backspace": "⌫",
    "Insert": "Einfg",
    "Home": "Pos1",
    "PageUp": "Bild↑",
    "Tab": "Tab",
    "Return": "Enter",
    "Delete": "Entf",
    "End": "Ende",
    "PageDown": "Bild↓",
    "CapsLock": "Caps",
    "LeftShift": "Shift",
    "RightShift": "Shift",
    "LeftCtrl": "Strg",
    "RightCtrl": "Strg",
    "Win": "Win",
    "LeftAlt": "Alt",
    "RightAlt": "AltGr",
    "Fn": "Fn",
    "Menu": "Menü",
    "Space": "Leertaste",
    "Up": "↑",
    "Down": "↓",
    "Left": "←",
    "Right": "→",
}

# Extra names people are likely to type.
ALIASES = {
    "Escape": ["esc"],
    "Return": ["enter"],
    "Space": ["space", "leer"],
    "CapsLock": ["caps"],
    "LeftShift": ["lshift"],
    "RightShift": ["rshift"],
    "LeftCtrl": ["lctrl", "strg"],
    "RightCtrl": ["rctrl"],
    "LeftAlt": ["alt", "lalt"],
    "RightAlt": ["altgr", "ralt"],
    "Up": ["up"],
    "Down": ["down"],
    "Left": ["left"],
    "Right": ["right"],
}


@dataclass(frozen=True)
class Key:
    index: int
    name: str  # US-positional name from the layout file
    label: str  # what's printed on the German key
    x: float
    y: float
    w: float
    h: float
    polygon: tuple[tuple[float, float], ...] | None = None  # for the L-shaped Enter


class Layout:
    def __init__(self, keys: list[Key]):
        self.keys = keys
        # Width / height of the keyboard picture, from a regular key's shape.
        self.aspect = statistics.median(k.h for k in keys) / statistics.median(k.w for k in keys)
        self._lookup = self._build_lookup()

    def _build_lookup(self) -> dict[str, Key]:
        """Printed labels first, so 'z' means the German Z key; then names and aliases."""
        lookup: dict[str, Key] = {}
        label_counts: dict[str, int] = {}
        for key in self.keys:
            label_counts[key.label.lower()] = label_counts.get(key.label.lower(), 0) + 1
        for key in self.keys:
            if label_counts[key.label.lower()] == 1:
                lookup[key.label.lower()] = key
        for key in self.keys:
            for alias in [key.name.lower(), *ALIASES.get(key.name, [])]:
                lookup.setdefault(alias, key)
        return lookup

    def find(self, name: str) -> Key | None:
        return self._lookup.get(name.strip().lower())


def load_layout(name: str = "iso_de") -> Layout:
    data = json.loads(resources.files(__package__).joinpath("layouts", f"{name}.json").read_text())
    keys = [
        Key(
            index=k["index"],
            name=k["name"],
            label=k.get("label_de") or SHORT_LABELS.get(k["name"], k["name"]),
            x=k["x"],
            y=k["y"],
            w=k["w"],
            h=k["h"],
            polygon=tuple(map(tuple, k["polygon"])) if "polygon" in k else None,
        )
        for k in data["keys"]
    ]
    return Layout(keys)

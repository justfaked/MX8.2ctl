"""Named presets of lighting and sleep settings, stored in the user's config folder."""

import dataclasses
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .keyboard import Keyboard
from .protocol import LightingSettings, SleepSettings, custom_colors_bytes

Color = tuple[int, int, int]
KeyColors = dict[int, Color]  # key index -> color


class PresetError(Exception):
    pass


def config_dir() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = config_home / "mx82ctl"
    # Earlier versions were called cherry-util; carry their presets over once.
    old = config_home / "cherry-util"
    if not path.exists() and old.is_dir():
        old.rename(path)
    return path


def presets_file() -> Path:
    return config_dir() / "presets.json"


def key_colors_file() -> Path:
    return config_dir() / "key_colors.json"


def _colors_to_json(colors: KeyColors) -> dict:
    return {str(index): "#{:02x}{:02x}{:02x}".format(*color) for index, color in sorted(colors.items())}


def _colors_from_json(data: dict) -> KeyColors:
    return {int(index): tuple(bytes.fromhex(value.removeprefix("#"))) for index, value in data.items()}


def load_key_colors() -> KeyColors:
    """The per-key colors last sent to the keyboard (it can't report them back)."""
    path = key_colors_file()
    if not path.exists():
        return {}
    try:
        return _colors_from_json(json.loads(path.read_text()))
    except (ValueError, AttributeError) as error:
        raise PresetError(f"Can't read {path}: {error}") from None


def set_key_colors(keyboard: Keyboard, colors: KeyColors) -> None:
    """Send per-key colors to the keyboard and remember them."""
    keyboard.write_custom_colors(custom_colors_bytes(colors))
    path = key_colors_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_colors_to_json(colors), indent=2) + "\n")


@dataclass
class Preset:
    lighting: LightingSettings
    sleep: SleepSettings
    key_colors: KeyColors = dataclasses.field(default_factory=dict)

    def to_json(self) -> dict:
        data = {"lighting": dataclasses.asdict(self.lighting), "sleep": dataclasses.asdict(self.sleep)}
        if self.key_colors:
            data["key_colors"] = _colors_to_json(self.key_colors)
        return data

    @classmethod
    def from_json(cls, data: dict) -> "Preset":
        lighting = dict(data["lighting"])
        lighting["color"] = tuple(lighting["color"])
        key_colors = _colors_from_json(data.get("key_colors", {}))
        return cls(LightingSettings(**lighting), SleepSettings(**data["sleep"]), key_colors)


def current_preset(keyboard: Keyboard) -> Preset:
    return Preset(lighting=keyboard.lighting(), sleep=keyboard.sleep_settings(), key_colors=load_key_colors())


def apply_preset(keyboard: Keyboard, preset: Preset) -> None:
    # Colors first, so switching to the custom effect shows the right ones.
    if preset.key_colors:
        set_key_colors(keyboard, preset.key_colors)
    keyboard.set_lighting(preset.lighting)
    keyboard.set_sleep_settings(preset.sleep)


class PresetStore:
    """All presets plus the name of the last one used."""

    def __init__(self, path: Path | None = None):
        self.path = path or presets_file()
        self.presets: dict[str, Preset] = {}
        self.last_used: str | None = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self.presets = {name: Preset.from_json(p) for name, p in data.get("presets", {}).items()}
                self.last_used = data.get("last_used")
            except (ValueError, KeyError, TypeError) as error:
                raise PresetError(f"Can't read {self.path}: {error}") from None

    def get(self, name: str) -> Preset:
        if name not in self.presets:
            available = ", ".join(sorted(self.presets)) or "none saved yet"
            raise PresetError(f"No preset called '{name}' (available: {available}).")
        return self.presets[name]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_used": self.last_used,
            "presets": {name: preset.to_json() for name, preset in sorted(self.presets.items())},
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(self.path)

"""Named presets of lighting and sleep settings, stored in the user's config folder."""

import dataclasses
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .protocol import LightingSettings, SleepSettings


class PresetError(Exception):
    pass


def presets_file() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_home / "cherry-util" / "presets.json"


@dataclass
class Preset:
    lighting: LightingSettings
    sleep: SleepSettings

    def to_json(self) -> dict:
        return {"lighting": dataclasses.asdict(self.lighting), "sleep": dataclasses.asdict(self.sleep)}

    @classmethod
    def from_json(cls, data: dict) -> "Preset":
        lighting = dict(data["lighting"])
        lighting["color"] = tuple(lighting["color"])
        return cls(LightingSettings(**lighting), SleepSettings(**data["sleep"]))


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

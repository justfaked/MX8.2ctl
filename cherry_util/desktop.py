"""App menu entry and login autostart for the tray icon."""

import os
import shutil
import sys
from pathlib import Path

ENTRY = """[Desktop Entry]
Type=Application
Name={name}
Comment=Lighting, sleep settings and battery for the CHERRY MX 8.2 TKL Wireless
Exec={command} {subcommand}
Icon=input-keyboard
Terminal=false
Categories=Settings;HardwareSettings;
"""


def _command() -> str:
    """The cherry-util command as the desktop will run it.

    Prefers the one on PATH, which inside distrobox is the exported wrapper
    that also works on the host.
    """
    found = shutil.which("cherry-util")
    if found:
        return found
    return str(Path(sys.argv[0]).resolve())


def install() -> list[Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    command = _command()
    files = {
        data_home / "applications" / "cherry-util.desktop": ENTRY.format(
            name="Cherry Keyboard Utility", command=command, subcommand="gui"
        ),
        config_home / "autostart" / "cherry-util-tray.desktop": ENTRY.format(
            name="Cherry Keyboard Utility (tray)", command=command, subcommand="tray"
        ),
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return list(files)

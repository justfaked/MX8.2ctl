"""Command-line entry point: `cherry-util <command>`."""

import argparse
import dataclasses
import sys

from .device import DeviceError, open_device
from .keyboard import Keyboard
from .layout import load_layout
from .presets import PresetError, PresetStore, apply_preset, current_preset, load_key_colors, set_key_colors
from .protocol import (
    BRIGHTNESS_RANGE,
    DIRECTION_NAMES,
    DIRECTIONS,
    EFFECT_NAMES,
    EFFECTS,
    HIBERNATE_OFF,
    HIBERNATE_RANGE,
    SLEEP_OFF,
    SLEEP_RANGE,
    USER_SPEED_RANGE,
    LightingSettings,
    SleepSettings,
    speed_from_user,
    speed_to_user,
)

COLORS = {
    "red": (255, 0, 0),
    "orange": (255, 96, 0),
    "yellow": (255, 200, 0),
    "green": (0, 255, 0),
    "cyan": (0, 255, 255),
    "blue": (0, 0, 255),
    "purple": (128, 0, 255),
    "pink": (255, 0, 128),
    "white": (255, 255, 255),
}


def cmd_info(keyboard: Keyboard, _args: argparse.Namespace) -> None:
    info = keyboard.device.info
    print(f"Found:   {info.name} (046a:{info.product_id:04x})")
    print(f"Device:  {info.path}")
    print("Connection opened successfully.")


def cmd_battery(keyboard: Keyboard, _args: argparse.Namespace) -> None:
    status = keyboard.battery()
    print(f"Battery: {status.percent}%" + (" (charging)" if status.charging else ""))


# --- sleep -----------------------------------------------------------------


def describe_sleep(settings: SleepSettings) -> str:
    sleep = "off" if settings.sleep_seconds == SLEEP_OFF else f"after {settings.sleep_seconds} seconds"
    hibernate = "off" if settings.hibernate_minutes == HIBERNATE_OFF else f"after {settings.hibernate_minutes} minutes"
    return f"Sleep:     {sleep}\nHibernate: {hibernate}"


def parse_timer(value: str, allowed: range, off: int, unit: str) -> int:
    if value == "off":
        return off
    if value.isdigit() and int(value) in allowed:
        return int(value)
    raise argparse.ArgumentTypeError(f"must be 'off' or {allowed.start}-{allowed.stop - 1} {unit}")


def cmd_sleep(keyboard: Keyboard, args: argparse.Namespace) -> None:
    settings = keyboard.sleep_settings()
    changes = {
        name: value
        for name, value in (("sleep_seconds", args.sleep), ("hibernate_minutes", args.hibernate))
        if value is not None
    }
    if changes:
        settings = keyboard.set_sleep_settings(dataclasses.replace(settings, **changes))
    print(describe_sleep(settings))


# --- lighting --------------------------------------------------------------


def describe_lighting(settings: LightingSettings) -> str:
    effect = EFFECT_NAMES.get(settings.effect, f"unknown ({settings.effect:#04x})")
    color = "rainbow" if settings.rainbow else "#{:02x}{:02x}{:02x}".format(*settings.color)
    direction = DIRECTION_NAMES.get(settings.direction, f"unknown ({settings.direction:#04x})")
    return (
        f"Lights:     {'on' if settings.enabled else 'off'}\n"
        f"Effect:     {effect}\n"
        f"Color:      {color}\n"
        f"Brightness: {settings.brightness} of {BRIGHTNESS_RANGE.stop - 1}\n"
        f"Speed:      {speed_to_user(settings.speed)} of {USER_SPEED_RANGE.stop - 1}\n"
        f"Direction:  {direction}"
    )


def parse_color(value: str) -> tuple[int, int, int]:
    if value in COLORS:
        return COLORS[value]
    hex_value = value.removeprefix("#")
    if len(hex_value) == 6:
        try:
            return tuple(bytes.fromhex(hex_value))
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"use a name ({', '.join(COLORS)}) or a hex code like ff8800")


def parse_number(value: str, allowed: range) -> int:
    if value.isdigit() and int(value) in allowed:
        return int(value)
    raise argparse.ArgumentTypeError(f"must be {allowed.start}-{allowed.stop - 1}")


def parse_speed(value: str) -> int:
    return speed_from_user(parse_number(value, USER_SPEED_RANGE))


def cmd_lighting(keyboard: Keyboard, args: argparse.Namespace) -> None:
    settings = keyboard.lighting()
    changes = {}
    if args.effect is not None:
        changes["effect"] = EFFECTS[args.effect]
    if args.color is not None:
        changes["color"] = args.color
        changes["rainbow"] = False
    if args.rainbow:
        changes["rainbow"] = True
    if args.brightness is not None:
        changes["brightness"] = args.brightness
    if args.speed is not None:
        changes["speed"] = args.speed
    if args.direction is not None:
        changes["direction"] = DIRECTIONS[args.direction]
    if args.off:
        changes["enabled"] = False
    elif changes or args.on:
        # Changing anything turns the lights on, like the Cherry Utility does.
        changes["enabled"] = True
    if changes:
        settings = keyboard.set_lighting(dataclasses.replace(settings, **changes))
    print(describe_lighting(settings))


# --- keys ------------------------------------------------------------------


def parse_key_assignment(value: str) -> tuple[list[str], tuple[int, int, int]]:
    """'w,a,s,d=red' -> (['w', 'a', 's', 'd'], (255, 0, 0))"""
    keys, sep, color = value.rpartition("=")
    if not sep or not keys:
        raise argparse.ArgumentTypeError("use KEYS=COLOR, e.g. w,a,s,d=red")
    return [k for k in keys.split(",") if k.strip()], parse_color(color)


def describe_key_colors(colors: dict[int, tuple[int, int, int]]) -> str:
    if not colors:
        return "No per-key colors set yet."
    layout = load_layout()
    by_color: dict[tuple[int, int, int], list[str]] = {}
    for key in sorted(layout.keys, key=lambda k: (round(k.y, 2), k.x)):
        if key.index in colors:
            by_color.setdefault(colors[key.index], []).append(key.label)
    lines = ["#{:02x}{:02x}{:02x}: ".format(*color) + " ".join(labels) for color, labels in by_color.items()]
    unset = len(layout.keys) - sum(1 for k in layout.keys if k.index in colors)
    if unset:
        lines.append(f"(dark: {unset} keys)")
    return "\n".join(lines)


def cmd_keys(keyboard: Keyboard, args: argparse.Namespace) -> None:
    if args.all is None and not args.set and not args.clear:
        print(describe_key_colors(load_key_colors()))
        return
    layout = load_layout()
    colors = {} if args.clear else load_key_colors()
    if args.all is not None:
        colors = {key.index: args.all for key in layout.keys}
    for names, color in args.set:
        for name in names:
            key = layout.find(name)
            if key is None:
                raise DeviceError(f"Unknown key '{name}'.")
            colors[key.index] = color
    set_key_colors(keyboard, colors)
    lighting = keyboard.lighting()
    if not lighting.enabled or lighting.effect != EFFECTS["custom"]:
        keyboard.set_lighting(dataclasses.replace(lighting, enabled=True, effect=EFFECTS["custom"]))
    print(describe_key_colors(colors))


# --- presets ---------------------------------------------------------------


def preset_name(value: str) -> str:
    if value and all(c.isalnum() or c in "-_" for c in value):
        return value
    raise argparse.ArgumentTypeError("use letters, digits, '-' or '_'")


def cmd_save(keyboard: Keyboard, args: argparse.Namespace) -> None:
    store = PresetStore()
    replaced = args.name in store.presets
    store.presets[args.name] = current_preset(keyboard)
    store.last_used = args.name
    store.save()
    print(f"{'Updated' if replaced else 'Saved'} preset '{args.name}' from the keyboard's current settings.")


def cmd_use(keyboard: Keyboard, args: argparse.Namespace) -> None:
    store = PresetStore()
    preset = store.get(args.name)
    apply_preset(keyboard, preset)
    store.last_used = args.name
    store.save()
    print(f"Using preset '{args.name}'.")


def cmd_presets(keyboard: Keyboard | None, _args: argparse.Namespace) -> None:
    store = PresetStore()
    if not store.presets:
        print("No presets saved yet. Set up the keyboard, then run: cherry-util save <name>")
        return
    current = current_preset(keyboard) if keyboard else None
    for name in sorted(store.presets):
        notes = []
        if name == store.last_used:
            notes.append("last used")
        if current == store.presets[name]:
            notes.append("matches keyboard")
        print(f"{name}" + (f"  ({', '.join(notes)})" if notes else ""))


def cmd_delete(_keyboard: None, args: argparse.Namespace) -> None:
    store = PresetStore()
    store.get(args.name)
    del store.presets[args.name]
    if store.last_used == args.name:
        store.last_used = None
    store.save()
    print(f"Deleted preset '{args.name}'.")


# --- app --------------------------------------------------------------------


def cmd_gui(_keyboard: None, args: argparse.Namespace) -> None:
    from . import gui  # Qt is only needed for the app

    gui.run(show_window=args.command == "gui")


def cmd_setup_desktop(_keyboard: None, _args: argparse.Namespace) -> None:
    from . import desktop

    for path in desktop.install():
        print(f"Wrote {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cherry-util")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("info", help="find the keyboard and check access").set_defaults(func=cmd_info)
    commands.add_parser("battery", help="show the battery level").set_defaults(func=cmd_battery)

    sleep = commands.add_parser("sleep", help="show or change the sleep and hibernate settings")
    sleep.add_argument(
        "--sleep",
        metavar="SECONDS",
        type=lambda v: parse_timer(v, SLEEP_RANGE, SLEEP_OFF, "seconds"),
        help="light sleep after 30-300 seconds, or 'off'",
    )
    sleep.add_argument(
        "--hibernate",
        metavar="MINUTES",
        type=lambda v: parse_timer(v, HIBERNATE_RANGE, HIBERNATE_OFF, "minutes"),
        help="deep sleep after 15-300 minutes, or 'off'",
    )
    sleep.set_defaults(func=cmd_sleep)

    lighting = commands.add_parser("lighting", help="show or change the lighting")
    lighting.add_argument("--effect", choices=EFFECTS, help="lighting effect")
    colors = lighting.add_mutually_exclusive_group()
    colors.add_argument("--color", type=parse_color, help=f"{', '.join(COLORS)}, or a hex code like ff8800")
    colors.add_argument("--rainbow", action="store_true", help="cycle through all colors instead of one color")
    switch = lighting.add_mutually_exclusive_group()
    switch.add_argument("--on", action="store_true", help="turn the lights on")
    switch.add_argument("--off", action="store_true", help="turn the lights off (settings are kept)")
    lighting.add_argument(
        "--brightness", type=lambda v: parse_number(v, BRIGHTNESS_RANGE), metavar="0-4", help="0 = dimmest, 4 = brightest"
    )
    lighting.add_argument("--speed", type=parse_speed, metavar="1-5", help="1 = slowest, 5 = fastest")
    lighting.add_argument("--direction", choices=DIRECTIONS, help="direction of the wave effect")
    lighting.set_defaults(func=cmd_lighting)

    keys = commands.add_parser(
        "keys",
        help="show or set per-key colors (switches the effect to 'custom')",
        description="Key names are the German labels (z, ö, ß, <, #, ...) or esc, enter, space, f1, ...",
    )
    keys.add_argument("--all", type=parse_color, metavar="COLOR", help="give every key this color first")
    keys.add_argument(
        "--set", type=parse_key_assignment, action="append", default=[], metavar="KEYS=COLOR",
        help="color some keys, e.g. w,a,s,d=red (repeatable)",
    )
    keys.add_argument("--clear", action="store_true", help="start from all keys dark instead of the current colors")
    keys.set_defaults(func=cmd_keys)

    save = commands.add_parser("save", help="save the keyboard's current lighting and sleep settings as a preset")
    save.add_argument("name", type=preset_name)
    save.set_defaults(func=cmd_save)
    use = commands.add_parser("use", help="apply a saved preset")
    use.add_argument("name")
    use.set_defaults(func=cmd_use)
    commands.add_parser("presets", help="list saved presets").set_defaults(func=cmd_presets, device="optional")
    delete = commands.add_parser("delete", help="delete a saved preset")
    delete.add_argument("name")
    delete.set_defaults(func=cmd_delete, device="none")

    commands.add_parser("gui", help="open the settings window (with tray icon)").set_defaults(func=cmd_gui, device="none")
    commands.add_parser("tray", help="run only the tray battery icon").set_defaults(func=cmd_gui, device="none")
    commands.add_parser(
        "setup-desktop", help="add an app menu entry and start the tray icon at login"
    ).set_defaults(func=cmd_setup_desktop, device="none")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    needs_device = getattr(args, "device", "required")
    try:
        if needs_device == "none":
            args.func(None, args)
            return
        try:
            device = open_device()
        except DeviceError:
            if needs_device != "optional":
                raise
            args.func(None, args)
            return
        with device:
            args.func(Keyboard(device), args)
    except (DeviceError, PresetError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

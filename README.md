# cherry-util

Configure the **CHERRY MX 8.2 TKL Wireless** keyboard on Linux. The official CHERRY Utility only runs on Windows.

It talks to the keyboard through its 2.4 GHz dongle and can:

- show the battery level
- change the sleep and hibernate timers
- change the lighting: effect, color, brightness, speed, direction, on/off
- save and switch between named presets

The keyboard stores all settings itself, so they survive power-off and work on any computer.

## Status

Early, personal project. Tested with one keyboard over the 2.4 GHz dongle (USB ID `046a:01c3`, "CHERRY MX 8.2 Xaga Dongle"). The USB cable and Bluetooth aren't supported yet.

## Requirements

- Linux with Python 3.11 or newer. There are no other dependencies.
- Read/write access to the dongle's `/dev/hidraw*` node. Bazzite grants this out of the box. On other distributions, add a udev rule on the host, for example `/etc/udev/rules.d/70-cherry-util.rules`:

  ```
  KERNEL=="hidraw*", ATTRS{idVendor}=="046a", ATTRS{idProduct}=="01c3", TAG+="uaccess"
  ```

  Then run `sudo udevadm control --reload && sudo udevadm trigger` and replug the dongle.

It works inside a distrobox/toolbox container too. The container sees the host's devices, but udev rules must be installed on the host.

## Installation

Clone the repository, then run `bin/cherry-util` from anywhere, or put it on your PATH:

```
ln -s "$PWD/bin/cherry-util" ~/.local/bin/cherry-util
```

When the checkout lives in a distrobox container, export the launcher so the host can run it too. The host then gets a `cherry-util` that runs inside the container:

```
distrobox-export --bin "$PWD/bin/cherry-util" --export-path ~/.local/bin
```

## Usage

```
cherry-util <command>
```

| Command | What it does |
|---|---|
| `info` | Find the keyboard and check access |
| `battery` | Show the battery level, and whether it's charging |
| `sleep` | Show the sleep and hibernate timers |
| `sleep --sleep 60 --hibernate 30` | Light sleep after 30–300 seconds, deep sleep after 15–300 minutes; `off` disables either |
| `lighting` | Show the current lighting |
| `lighting --effect breathing --color blue` | Change the lighting (options below) |
| `lighting --off` / `--on` | Turn the lights off or on. Other settings are kept |
| `save <name>` | Save the current lighting and sleep settings as a preset |
| `use <name>` | Apply a preset |
| `presets` | List presets |
| `delete <name>` | Delete a preset |

Lighting options can be combined:

- `--effect`: wave, spectrum, breathing, static, radar, vortex, fire, stars, sine-wave, rolling, rain, curve, red-hot-metal, wave-mid, scan, radiation, ripples, single-key, xaga
- `--color`: red, orange, yellow, green, cyan, blue, purple, pink, white, or a hex code like `ff8800`
- `--rainbow`: cycle through all colors instead of using one
- `--brightness`: 0 (dimmest) to 4 (brightest)
- `--speed`: 1 (slowest) to 5 (fastest)
- `--direction`: left or right (wave effect)

Presets are stored in `~/.config/cherry-util/presets.json`.

## Safety

The tool only sends commands that other projects have confirmed or that the official CHERRY Utility itself uses. Before every change, it reads the current values and refuses to write if they look unexpected. After writing, it reads them back to confirm. It never sends anything that resembles a firmware update or raw memory write.

## Credits

The protocol knowledge comes from:

- [cherryrgb-rs](https://github.com/skraus-dev/cherryrgb-rs): lighting packets and effect IDs
- [OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB): EVision protocol and the MX 8.2 USB captures in issue #3942
- [cherry-battery-state](https://github.com/zcmk123/cherry-battery-state) and [BatteryTool](https://github.com/1gcat/BatteryTool): battery query
- Static analysis of the official CHERRY Utility 3.12: sleep timers, the lights on/off flag and this keyboard's effect list

Not affiliated with CHERRY.

## License

GPL-3.0. See [LICENSE](LICENSE).

# CHERRY MX 8.2 TKL Wireless: configuration protocol

This document describes what `mx82ctl` sends to the keyboard and where each fact comes from. The protocol is CHERRY's variant of the EVision protocol, which is also used by other keyboards built on EVision/Sonix controllers.

Sources are marked:

- **[device]**: confirmed on a real MX 8.2 TKL Wireless (XAGA) through the dongle `046a:01c3`, firmware/hardware version `0x0102`.
- **[utility]**: found by static analysis of the official CHERRY Utility 3.12 for Windows (`cherry-utility-software-x32-3-12.exe`).
- **[cherryrgb]**: [cherryrgb-rs](https://github.com/skraus-dev/cherryrgb-rs).
- **[openrgb]**: [OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) `EVisionV2KeyboardController`.
- **[battery-tools]**: [cherry-battery-state](https://github.com/zcmk123/cherry-battery-state) and [BatteryTool](https://github.com/1gcat/BatteryTool).

## Transport

| | |
|---|---|
| Device | Dongle `046a:01c3` "CHERRY MX 8.2 Xaga Dongle" (the keyboard itself is `046a:01c2`) |
| Interface | One USB HID interface, also used for typing. Linux exposes it as one `/dev/hidrawN` |
| Channel | Report ID `0x04`, vendor usage page `0xFF1C`, usage `0x92`: 63-byte output and input reports |

Configuration goes over the same hidraw node as normal typing, so a reader must skip keyboard reports and only look at report `0x04` replies [device]. Using hidraw (not libusb) keeps typing working while the tool runs.

## Packet format

Every request and reply is 64 bytes, including the report ID [utility, openrgb, device]:

| Byte | Meaning |
|---|---|
| 0 | Report ID `0x04` |
| 1–2 | Checksum, u16 little-endian: sum of bytes 3–63 |
| 3 | Command |
| 4 | Data length (max 56) |
| 5–6 | Offset, u16 little-endian |
| 7 | `0x55` in table writes, `0x00` otherwise. In replies: status, where non-zero means error for reads |
| 8–63 | Data, zero-padded |

Replies echo the command, length and offset. Writes are wrapped in a session: begin (`0x01`), one or more writes, end (`0x02`) [utility]. Reads need no session.

## Commands

| Byte | Name | Used for |
|---|---|---|
| `0x01` | Begin (STX) | Start a write session |
| `0x02` | End (ETX) | End a write session |
| `0x05` | Read config table | Read settings |
| `0x06` | Write config table | Lighting, on/off, sleep |
| `0x0A` | Read custom colors | Exists in the Utility's command table; never used by it; untested |
| `0x0B` | Write custom colors | Per-key colors |
| `0x1A` | Read battery | Battery level |
| `0xAA` | Dongle state | Also how the dongle acknowledges `0x0B` writes, see below |

The Utility also lists key mapping (`0x07`–`0x09`) and macro (`0x14`, `0x15`) commands. `mx82ctl` doesn't use them.

## Config table

The MX 8.2 TKL has no hardware profiles, so everything sits at fixed offsets [utility]:

| Offset | Size | Meaning | Source |
|---|---|---|---|
| `0x01` | 1 | Effect (see below). Bit `0x40` is an audio-reactive overlay flag | utility, device |
| `0x02` | 1 | Brightness 0–4 | utility, device |
| `0x03` | 1 | Speed ("delay") 0 = fastest … 4 = slowest | utility, cherryrgb |
| `0x04` | 1 | Direction: right `0`, left `1` (the Utility offers these for Wave only) | utility |
| `0x05` | 1 | Random/rainbow color flag | utility |
| `0x06`–`0x08` | 3 | Color R, G, B | utility, device |
| `0x15` | 1 | Lights disabled: `1` = off, `0` = on | utility, device |
| `0x22` | 2 | Sleep delay, seconds, u16 LE: 30–300, `0` = off | utility, device |
| `0x24` | 2 | Hibernate delay, minutes, u16 LE: 15–300, `4320` (72 h) = off | utility, device |

Offset `0x00` is never written by the Utility. cherryrgb-rs writes its lighting block starting at `0x00` with a leading zero byte, which lands on the same fields.

The Utility writes the 8-byte header at `0x01` as a whole. To turn the lights off it writes only `0x15 = 1`; to turn them on it writes `0x15 = 0` and then the header [utility]. The keyboard applies changes immediately and keeps them after power-off [device].

### Effects

From the Utility's "Regular" mapping table, limited to the modes it lists for this keyboard [utility]. Spectrum, Static, Custom and XAGA were confirmed on the device.

| Byte | Effect | Byte | Effect |
|---|---|---|---|
| `0x00` | Wave | `0x0B` | Rain |
| `0x01` | Spectrum | `0x0C` | Curve |
| `0x02` | Breathing | `0x0D` | RedHotMetal |
| `0x03` | Static | `0x0E` | WaveMid |
| `0x04` | Radar | `0x0F` | Scan |
| `0x05` | Vortex | `0x12` | Radiation |
| `0x06` | Fire | `0x13` | Ripples |
| `0x07` | Stars | `0x15` | SingleKey |
| `0x08` | Custom (per-key colors) | `0x16` | XAGA |
| `0x09` | SineWave | | |
| `0x0A` | Rolling | | |

### Example: set sleep to 30 s and hibernate to 15 min

```
04 01 00 01 …                    begin
04 9d 00 06 02 22 00 55 1e 00 …  write 2 bytes at 0x22: 30
04 90 00 06 02 24 00 55 0f 00 …  write 2 bytes at 0x24: 15
04 02 00 02 …                    end
```

## Per-key colors

A table of 126 slots × 3 bytes (R, G, B) = 378 bytes, written with `0x0B` in 56-byte chunks at offsets 0, 56, …, 336 (the last chunk is 42 bytes), inside a begin/end session, with `0x55` in byte 7 [utility, cherryrgb]. The colors show when the effect is Custom (`0x08`). Unused slots should be black.

**Dongle quirk [device]:** the dongle answers each `0x0B` chunk with command byte `0xAA` instead of `0x0B`, but echoes the length, offset, marker and data. The colors do arrive on the keyboard. A reader waiting for an echo of `0x0B` times out.

A key's slot is its `keyIndex` in the Utility's layout data [utility, device]. Slots run column by column, six per column (Esc = 0, `^` = 1, Tab = 2, Caps = 3, left Shift = 4, left Ctrl = 5, 1 = 7, …). The German ISO layout with positions is in [`mx82ctl/layouts/iso_de.json`](../mx82ctl/layouts/iso_de.json). ISO-only keys: `<` = 10, `#` = 75. ANSI boards use slot 80 for Backslash instead.

The keyboard can't be asked for its current per-key colors through any command the Utility uses.

## Battery

Request `04 20 00 1A 06 00 …` (command `0x1A`, length 6) [battery-tools, device]. Reply:

| Byte | Meaning |
|---|---|
| 3 | `0x1A` |
| 7 | Status: `0xFF` = error (e.g. keyboard asleep) |
| 8 | Battery percent |
| 9 | Non-zero while charging |

The Utility treats 25 % as low and 5 % as critical for this keyboard [utility].

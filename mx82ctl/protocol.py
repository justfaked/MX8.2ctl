"""Packet format of the configuration channel (HID report ID 4).

Layout, taken from the Cherry Utility (EVision protocol):
    [0]    report ID (0x04)
    [1..2] checksum, u16 little-endian: sum of bytes [3..63]
    [3]    command
    [4]    data length
    [5..6] offset, u16 little-endian
    [7]    extra byte (0x55 for table writes, 0x00 otherwise)
    [8..]  data, zero-padded to 64 bytes
"""

from dataclasses import dataclass

REPORT_ID = 0x04
PACKET_SIZE = 64
MAX_DATA = PACKET_SIZE - 8

CMD_BEGIN_CONFIGURE = 0x01
CMD_END_CONFIGURE = 0x02
CMD_READ_CONFIG = 0x05
CMD_WRITE_CONFIG = 0x06
CMD_WRITE_CUSTOM_COLORS = 0x0B
CMD_READ_BATTERY = 0x1A
# The dongle answers custom color writes (0x0B) with this command byte
# instead of echoing 0x0B; offset and data are echoed as usual. Observed on
# the XAGA dongle; the colors do arrive on the keyboard.
CMD_DONGLE_ACK = 0xAA

STATUS_ERROR = 0xFF

# Marker the Cherry Utility puts in byte [7] of config-table writes.
WRITE_MARKER = 0x55


def build_packet(command: int, length: int = 0, offset: int = 0, extra: int = 0, data: bytes = b"") -> bytes:
    body = bytearray(PACKET_SIZE)
    body[0] = REPORT_ID
    body[3] = command
    body[4] = length
    body[5:7] = offset.to_bytes(2, "little")
    body[7] = extra
    body[8 : 8 + len(data)] = data
    body[1:3] = (sum(body[3:]) & 0xFFFF).to_bytes(2, "little")
    return bytes(body)


def is_reply_to(packet: bytes, command: int | tuple[int, ...], offset: int | None = None) -> bool:
    commands = command if isinstance(command, tuple) else (command,)
    return (
        len(packet) >= 8
        and packet[0] == REPORT_ID
        and packet[3] in commands
        and (offset is None or int.from_bytes(packet[5:7], "little") == offset)
    )


def reply_data(reply: bytes) -> bytes | None:
    """Payload of a config-table reply, or None if the keyboard reported an error."""
    if reply[7] != 0 or reply[4] > MAX_DATA:
        return None
    return reply[8 : 8 + reply[4]]


BEGIN_CONFIGURE = build_packet(CMD_BEGIN_CONFIGURE)
END_CONFIGURE = build_packet(CMD_END_CONFIGURE)


def read_config_packet(offset: int, length: int) -> bytes:
    return build_packet(CMD_READ_CONFIG, length=length, offset=offset)


def write_packet(command: int, offset: int, data: bytes) -> bytes:
    """Table write (config or custom colors), as the Cherry Utility sends it."""
    return build_packet(command, length=len(data), offset=offset, extra=WRITE_MARKER, data=data)


# --- Battery ---------------------------------------------------------------

# Battery query, confirmed on other Cherry dongles by cherry-battery-state and BatteryTool:
# sends 04 20 00 1A 06 ..., reply has a status byte at [7], percent at [8], charging at [9].
BATTERY_QUERY = build_packet(CMD_READ_BATTERY, length=6)


@dataclass
class BatteryStatus:
    percent: int
    charging: bool


def parse_battery(reply: bytes) -> BatteryStatus | None:
    """Return None if the reply isn't a usable battery reading (e.g. keyboard asleep)."""
    if len(reply) < 10 or reply[7] == STATUS_ERROR or not 1 <= reply[8] <= 100:
        return None
    return BatteryStatus(percent=reply[8], charging=reply[9] != 0)


# --- Sleep -----------------------------------------------------------------

# Sleep settings in the config table, found in Cherry Utility 3.12
# (DeviceSleepMode_Evision). Both are u16 little-endian.
OFFSET_SLEEP = 0x22  # seconds, 30-300; 0 = off; followed by hibernate at 0x24
SLEEP_SIZE = 4
SLEEP_RANGE = range(30, 301)
HIBERNATE_RANGE = range(15, 301)
SLEEP_OFF = 0
HIBERNATE_OFF = 4320  # minutes (72 h)


@dataclass
class SleepSettings:
    sleep_seconds: int  # SLEEP_OFF = off
    hibernate_minutes: int  # HIBERNATE_OFF = off

    def looks_sensible(self) -> bool:
        return (self.sleep_seconds == SLEEP_OFF or self.sleep_seconds in SLEEP_RANGE) and (
            self.hibernate_minutes == HIBERNATE_OFF or self.hibernate_minutes in HIBERNATE_RANGE
        )

    def to_bytes(self) -> bytes:
        return self.sleep_seconds.to_bytes(2, "little") + self.hibernate_minutes.to_bytes(2, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "SleepSettings":
        return cls(int.from_bytes(data[0:2], "little"), int.from_bytes(data[2:4], "little"))


# --- Lighting --------------------------------------------------------------

# Lighting in the config table, found in Cherry Utility 3.12 (Lightings_Evision)
# and confirmed on this keyboard by changing effect, brightness and on/off with
# Fn keys and diffing the table:
#   0x01 effect, 0x02 brightness, 0x03 speed, 0x04 direction,
#   0x05 rainbow flag, 0x06-0x08 color (r, g, b)
#   0x15 lights disabled flag (1 = off, 0 = on)
OFFSET_LIGHTING = 0x01
LIGHTING_SIZE = 8
OFFSET_LIGHTS_DISABLED = 0x15

BRIGHTNESS_RANGE = range(0, 5)  # 0 = dimmest, 4 = full
SPEED_RANGE = range(0, 5)  # 0 = fastest, 4 = slowest
USER_SPEED_RANGE = range(1, SPEED_RANGE.stop + 1)  # shown to users: 1 = slowest, 5 = fastest


def speed_to_user(speed: int) -> int:
    return SPEED_RANGE.stop - speed


def speed_from_user(user_speed: int) -> int:
    return SPEED_RANGE.stop - user_speed

# Effect IDs from the Cherry Utility's "Regular" mapping table, limited to the
# modes it lists for this keyboard. The ones cherryrgb-rs also has match its IDs.
EFFECTS = {
    "wave": 0x00,
    "spectrum": 0x01,
    "breathing": 0x02,
    "static": 0x03,
    "radar": 0x04,
    "vortex": 0x05,
    "fire": 0x06,
    "stars": 0x07,
    "custom": 0x08,  # per-key colors from the custom color table
    "sine-wave": 0x09,
    "rolling": 0x0A,
    "rain": 0x0B,
    "curve": 0x0C,
    "red-hot-metal": 0x0D,
    "wave-mid": 0x0E,
    "scan": 0x0F,
    "radiation": 0x12,
    "ripples": 0x13,
    "single-key": 0x15,
    "xaga": 0x16,
}
EFFECT_NAMES = {value: name for name, value in EFFECTS.items()}

# Directions the Cherry Utility offers for this keyboard (Wave only).
DIRECTIONS = {"right": 0x00, "left": 0x01}
DIRECTION_NAMES = {value: name for name, value in DIRECTIONS.items()}


@dataclass
class LightingSettings:
    enabled: bool
    effect: int
    brightness: int
    speed: int
    direction: int
    rainbow: bool
    color: tuple[int, int, int]

    def looks_sensible(self) -> bool:
        return self.brightness in BRIGHTNESS_RANGE and self.speed in SPEED_RANGE

    def header_bytes(self) -> bytes:
        return bytes([self.effect, self.brightness, self.speed, self.direction, int(self.rainbow), *self.color])

    @classmethod
    def from_bytes(cls, header: bytes, disabled: int) -> "LightingSettings":
        return cls(
            enabled=disabled == 0,
            effect=header[0],
            brightness=header[1],
            speed=header[2],
            direction=header[3],
            rainbow=header[4] != 0,
            color=(header[5], header[6], header[7]),
        )


# --- Per-key colors ------------------------------------------------------------

# Custom color table written with cmd 0x0B, found in Cherry Utility 3.12
# (prepareCustomColors) and matching cherryrgb-rs: 126 slots of R, G, B.
# A key's slot is its "index" in the layout file. Unused slots stay black.
KEY_SLOTS = 126
CUSTOM_COLORS_SIZE = KEY_SLOTS * 3


def custom_colors_bytes(colors: dict[int, tuple[int, int, int]]) -> bytes:
    table = bytearray(CUSTOM_COLORS_SIZE)
    for index, (r, g, b) in colors.items():
        if not 0 <= index < KEY_SLOTS:
            raise ValueError(f"key index {index} out of range")
        table[3 * index : 3 * index + 3] = bytes((r, g, b))
    return bytes(table)

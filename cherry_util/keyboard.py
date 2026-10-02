"""High-level operations on the keyboard: battery, sleep and lighting."""

from .device import Device, DeviceError
from .protocol import (
    BATTERY_QUERY,
    BEGIN_CONFIGURE,
    CMD_BEGIN_CONFIGURE,
    CMD_DONGLE_ACK,
    CMD_END_CONFIGURE,
    CMD_READ_BATTERY,
    CMD_READ_CONFIG,
    CMD_WRITE_CONFIG,
    CMD_WRITE_CUSTOM_COLORS,
    MAX_DATA,
    END_CONFIGURE,
    LIGHTING_SIZE,
    OFFSET_LIGHTING,
    OFFSET_LIGHTS_DISABLED,
    OFFSET_SLEEP,
    SLEEP_SIZE,
    WRITE_MARKER,
    BatteryStatus,
    LightingSettings,
    SleepSettings,
    parse_battery,
    read_config_packet,
    reply_data,
    write_packet,
)

ASLEEP_HINT = "The keyboard didn't answer. It may be asleep: press a key and try again."


class Keyboard:
    def __init__(self, device: Device):
        self.device = device

    # --- Raw config table ---------------------------------------------------

    def read_config(self, offset: int, length: int) -> bytes:
        reply = self.device.request(read_config_packet(offset, length), CMD_READ_CONFIG, offset)
        if reply is None:
            raise DeviceError(ASLEEP_HINT)
        data = reply_data(reply)
        if data is None or len(data) < length:
            raise DeviceError(f"The keyboard rejected the request (reply: {reply[:8].hex(' ')}).")
        return data

    def write_config(self, *writes: tuple[int, bytes]) -> None:
        """Write (offset, data) pairs to the config table in one begin/end session."""
        self._write_session([(CMD_WRITE_CONFIG, offset, data) for offset, data in writes])

    def write_custom_colors(self, table: bytes) -> None:
        """Write the whole per-key color table in 56-byte chunks, in one session."""
        chunks = [
            (CMD_WRITE_CUSTOM_COLORS, offset, table[offset : offset + MAX_DATA])
            for offset in range(0, len(table), MAX_DATA)
        ]
        self._write_session(chunks)

    def _write_session(self, writes: list[tuple[int, int, bytes]]) -> None:
        """Send (command, offset, data) writes wrapped in begin/end, like the Cherry Utility does."""
        if self.device.request(BEGIN_CONFIGURE, CMD_BEGIN_CONFIGURE) is None:
            raise DeviceError(ASLEEP_HINT)
        try:
            for command, offset, data in writes:
                expected = (command, CMD_DONGLE_ACK) if command == CMD_WRITE_CUSTOM_COLORS else command
                reply = self.device.request(write_packet(command, offset, data), expected, offset)
                if reply is None or reply[7] not in (0, WRITE_MARKER):
                    raise DeviceError("The keyboard didn't accept the new setting.")
        finally:
            self.device.request(END_CONFIGURE, CMD_END_CONFIGURE)

    # --- Battery ------------------------------------------------------------

    def battery(self) -> BatteryStatus:
        reply = self.device.request(BATTERY_QUERY, CMD_READ_BATTERY)
        status = parse_battery(reply) if reply else None
        if status is None:
            raise DeviceError(ASLEEP_HINT)
        return status

    # --- Settings with read-check-write-verify ------------------------------

    def sleep_settings(self) -> SleepSettings:
        return _checked(SleepSettings.from_bytes(self.read_config(OFFSET_SLEEP, SLEEP_SIZE)), "sleep")

    def set_sleep_settings(self, wanted: SleepSettings) -> SleepSettings:
        self.sleep_settings()  # safety check before writing
        self.write_config((OFFSET_SLEEP, wanted.to_bytes()))
        return _verified(self.sleep_settings(), wanted)

    def lighting(self) -> LightingSettings:
        header = self.read_config(OFFSET_LIGHTING, LIGHTING_SIZE)
        disabled = self.read_config(OFFSET_LIGHTS_DISABLED, 1)[0]
        if disabled not in (0, 1):
            raise DeviceError(f"Unexpected lighting on/off value ({disabled}). Not touching it.")
        return _checked(LightingSettings.from_bytes(header, disabled), "lighting")

    def set_lighting(self, wanted: LightingSettings) -> LightingSettings:
        current = self.lighting()  # safety check before writing
        # Same order as the Cherry Utility: set the on/off flag first, then the header.
        # Turning off with nothing else changed only sets the flag, like the Cherry Utility.
        writes = [(OFFSET_LIGHTS_DISABLED, b"\x00" if wanted.enabled else b"\x01")]
        if wanted.enabled or wanted.header_bytes() != current.header_bytes():
            writes.append((OFFSET_LIGHTING, wanted.header_bytes()))
        self.write_config(*writes)
        return _verified(self.lighting(), wanted)


def _checked(settings, what: str):
    if not settings.looks_sensible():
        raise DeviceError(f"Unexpected {what} values ({settings}). Not touching them.")
    return settings


def _verified(result, wanted):
    if result != wanted:
        raise DeviceError(f"The keyboard reports different values than requested: {result}")
    return result

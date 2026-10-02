"""Finding and opening the keyboard's hidraw node."""

import os
import select
import time
from dataclasses import dataclass
from pathlib import Path

from .protocol import is_reply_to

CHERRY_VENDOR_ID = 0x046A

# All supported devices, keyed by USB product ID.
SUPPORTED_PRODUCTS = {
    0x01C3: "CHERRY MX 8.2 Xaga Dongle",
}

# Vendor usage page that carries the configuration channel (report ID 4).
CONFIG_USAGE_PAGE = 0xFF1C

HIDRAW_SYSFS = Path("/sys/class/hidraw")


class DeviceError(Exception):
    pass


@dataclass
class DeviceInfo:
    path: Path
    product_id: int
    name: str


def _parse_hid_id(uevent: str) -> tuple[int, int] | None:
    for line in uevent.splitlines():
        if line.startswith("HID_ID="):
            _bus, vendor, product = line.removeprefix("HID_ID=").split(":")
            return int(vendor, 16), int(product, 16)
    return None


def _has_usage_page(descriptor: bytes, page: int) -> bool:
    """Walk the HID report descriptor looking for a Usage Page item."""
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == 0xFE:  # long item: 0xFE, size, tag, data...
            i += 3 + descriptor[i + 1]
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        if prefix & 0xFC == 0x04:  # global item, tag 0 = Usage Page
            if int.from_bytes(descriptor[i + 1 : i + 1 + size], "little") == page:
                return True
        i += 1 + size
    return False


def find_device() -> DeviceInfo:
    """Return the first supported keyboard that exposes the config channel."""
    for node in sorted(HIDRAW_SYSFS.glob("hidraw*")):
        ids = _parse_hid_id((node / "device" / "uevent").read_text())
        if ids is None:
            continue
        vendor, product = ids
        if vendor != CHERRY_VENDOR_ID or product not in SUPPORTED_PRODUCTS:
            continue
        descriptor = (node / "device" / "report_descriptor").read_bytes()
        if not _has_usage_page(descriptor, CONFIG_USAGE_PAGE):
            continue
        return DeviceInfo(Path("/dev") / node.name, product, SUPPORTED_PRODUCTS[product])
    raise DeviceError(
        "No supported CHERRY keyboard found. Is the 2.4 GHz dongle plugged in "
        "and the keyboard switched to 2.4 GHz mode?"
    )


class Device:
    """An open connection to the keyboard. Use as a context manager."""

    def __init__(self, info: DeviceInfo):
        self.info = info
        self._fd: int | None = None

    def __enter__(self) -> "Device":
        try:
            self._fd = os.open(self.info.path, os.O_RDWR)
        except PermissionError:
            raise DeviceError(
                f"No permission to open {self.info.path}. A udev rule on the "
                "Bazzite host is needed to grant access."
            ) from None
        return self

    def _drain(self) -> None:
        """Discard input that arrived before our request (e.g. keypresses)."""
        while select.select([self._fd], [], [], 0)[0]:
            os.read(self._fd, 256)

    def request(self, packet: bytes, command: int, offset: int | None = None, timeout: float = 3.0) -> bytes | None:
        """Send a packet and wait for the reply to `command`. None on timeout."""
        self._drain()
        os.write(self._fd, packet)
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            if not select.select([self._fd], [], [], remaining)[0]:
                break
            reply = os.read(self._fd, 256)
            # The same node also carries normal typing; skip everything else.
            if is_reply_to(reply, command, offset):
                return reply
        return None

    def __exit__(self, *exc) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def open_device() -> Device:
    return Device(find_device())

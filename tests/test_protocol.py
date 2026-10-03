"""Offline tests: packet bytes and parsing, checked against bytes seen on a real keyboard."""

import unittest

from mx82ctl.layout import load_layout
from mx82ctl.protocol import (
    BATTERY_QUERY,
    BEGIN_CONFIGURE,
    BatteryStatus,
    BatteryWarning,
    CMD_DONGLE_ACK,
    CMD_WRITE_CONFIG,
    CMD_WRITE_CUSTOM_COLORS,
    CUSTOM_COLORS_SIZE,
    END_CONFIGURE,
    LightingSettings,
    SleepSettings,
    custom_colors_bytes,
    is_reply_to,
    parse_battery,
    read_config_packet,
    reply_data,
    speed_from_user,
    speed_to_user,
    write_packet,
)


def head(packet: bytes, n: int) -> str:
    return packet[:n].hex(" ")


class PacketTests(unittest.TestCase):
    def test_every_packet_is_64_bytes(self):
        for packet in (BATTERY_QUERY, BEGIN_CONFIGURE, END_CONFIGURE, read_config_packet(0x22, 4)):
            self.assertEqual(len(packet), 64)

    def test_battery_query(self):
        self.assertEqual(head(BATTERY_QUERY, 8), "04 20 00 1a 06 00 00 00")

    def test_begin_and_end(self):
        self.assertEqual(head(BEGIN_CONFIGURE, 4), "04 01 00 01")
        self.assertEqual(head(END_CONFIGURE, 4), "04 02 00 02")

    def test_read_sleep_settings(self):
        self.assertEqual(head(read_config_packet(0x22, 4), 8), "04 2b 00 05 04 22 00 00")

    def test_write_sleep_and_hibernate(self):
        self.assertEqual(head(write_packet(CMD_WRITE_CONFIG, 0x22, bytes([30, 0])), 10), "04 9d 00 06 02 22 00 55 1e 00")
        self.assertEqual(head(write_packet(CMD_WRITE_CONFIG, 0x24, bytes([15, 0])), 10), "04 90 00 06 02 24 00 55 0f 00")
        off = (4320).to_bytes(2, "little")
        self.assertEqual(head(write_packet(CMD_WRITE_CONFIG, 0x24, off), 10), "04 71 01 06 02 24 00 55 e0 10")

    def test_checksum_covers_whole_packet(self):
        packet = write_packet(CMD_WRITE_CUSTOM_COLORS, 0, bytes([0, 255, 0]))
        self.assertEqual(int.from_bytes(packet[1:3], "little"), sum(packet[3:]))


class ReplyTests(unittest.TestCase):
    def test_battery_reply(self):
        reply = bytes.fromhex("04 20 00 1a 06 00 00 00 5b 01".replace(" ", "")) + bytes(54)
        status = parse_battery(reply)
        self.assertEqual((status.percent, status.charging), (91, True))

    def test_battery_error_status(self):
        reply = bytes.fromhex("04 20 00 1a 06 00 00 ff 00 00".replace(" ", "")) + bytes(54)
        self.assertIsNone(parse_battery(reply))

    def test_sleep_reply(self):
        reply = bytes.fromhex("04 2b 00 05 04 22 00 00 00 00 e0 10".replace(" ", "")) + bytes(52)
        self.assertTrue(is_reply_to(reply, 0x05, 0x22))
        self.assertEqual(SleepSettings.from_bytes(reply_data(reply)), SleepSettings(0, 4320))

    def test_reply_offset_must_match(self):
        reply = bytes.fromhex("04 2b 00 05 04 22 00 00".replace(" ", "")) + bytes(56)
        self.assertFalse(is_reply_to(reply, 0x05, 0x24))

    def test_dongle_acknowledges_color_writes_with_aa(self):
        reply = bytes.fromhex("04 aa 01 aa 38 00 00 55 00 ff 00".replace(" ", "")) + bytes(53)
        self.assertTrue(is_reply_to(reply, (CMD_WRITE_CUSTOM_COLORS, CMD_DONGLE_ACK), 0))
        self.assertFalse(is_reply_to(reply, CMD_WRITE_CUSTOM_COLORS, 0))

    def test_typing_reports_are_not_replies(self):
        keypress = bytes([0x01, 0, 0, 0x04]) + bytes(60)
        self.assertFalse(is_reply_to(keypress, 0x05))


class SettingsTests(unittest.TestCase):
    def test_lighting_round_trip(self):
        # Read from a keyboard set to Spectrum, brightness 2, slowest speed.
        header = bytes.fromhex("01 02 04 01 00 96 96 9a".replace(" ", ""))
        lighting = LightingSettings.from_bytes(header, disabled=0)
        self.assertEqual((lighting.effect, lighting.brightness, lighting.speed), (0x01, 2, 4))
        self.assertTrue(lighting.enabled)
        self.assertEqual(lighting.header_bytes(), header)

    def test_speed_is_shown_slowest_first(self):
        self.assertEqual(speed_to_user(4), 1)
        self.assertEqual(speed_to_user(0), 5)
        self.assertEqual(speed_from_user(speed_to_user(3)), 3)

    def test_sleep_sanity_check(self):
        self.assertTrue(SleepSettings(30, 15).looks_sensible())
        self.assertTrue(SleepSettings(0, 4320).looks_sensible())
        self.assertFalse(SleepSettings(10, 15).looks_sensible())


class KeyColorTests(unittest.TestCase):
    def test_table_layout(self):
        table = custom_colors_bytes({0: (255, 0, 0), 10: (0, 0, 255)})
        self.assertEqual(len(table), CUSTOM_COLORS_SIZE)
        self.assertEqual(table[0:3], bytes([255, 0, 0]))
        self.assertEqual(table[30:33], bytes([0, 0, 255]))
        self.assertEqual(sum(table), 510)

    def test_german_layout(self):
        layout = load_layout()
        self.assertEqual(len(layout.keys), 88)
        # Confirmed on the device: Esc, the ISO keys, and German Y/Z.
        self.assertEqual(layout.find("esc").index, 0)
        self.assertEqual(layout.find("<").index, 10)
        self.assertEqual(layout.find("#").index, 75)
        self.assertEqual(layout.find("y").name, "Z")
        self.assertEqual(layout.find("z").name, "Y")
        self.assertEqual(len({k.index for k in layout.keys}), 88)


class BatteryWarningTests(unittest.TestCase):
    def levels(self, *readings):
        """Feed readings (percent, or (percent, charging), or None) and return which ones warned."""
        warning = BatteryWarning()
        result = []
        for reading in readings:
            if reading is None:
                status = None
            elif isinstance(reading, tuple):
                status = BatteryStatus(*reading)
            else:
                status = BatteryStatus(reading, False)
            result.append(warning.update(status) is not None)
        return result

    def test_warns_once_when_low_and_once_when_critical(self):
        self.assertEqual(self.levels(30, 25, 20, 10, 5, 4, 3), [False, True, False, False, True, False, False])

    def test_starting_critical_warns_once(self):
        self.assertEqual(self.levels(3, 2), [True, False])

    def test_missing_reading_keeps_state(self):
        self.assertEqual(self.levels(20, None, 19), [True, False, False])

    def test_charging_resets(self):
        self.assertEqual(self.levels(20, (21, True), 20), [True, False, True])

    def test_back_above_low_resets(self):
        self.assertEqual(self.levels(25, 26, 25), [True, False, True])

    def test_never_warns_while_charging(self):
        self.assertEqual(self.levels((3, True), (20, True)), [False, False])

    def test_messages(self):
        warning = BatteryWarning()
        self.assertIn("low: 20%", warning.update(BatteryStatus(20, False)))
        self.assertIn("critical: 5%", warning.update(BatteryStatus(5, False)))


if __name__ == "__main__":
    unittest.main()

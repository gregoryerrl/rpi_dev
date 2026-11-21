import unittest
from unittest.mock import patch

import hotspot
from provision import make_open


class HotspotTests(unittest.TestCase):
    @patch("hotspot.nm")
    @patch("hotspot.time.monotonic", return_value=100)
    def test_offline_waits_then_activates(self, clock, nm):
        nm.return_value = "wlan0:wifi:disconnected:\nlo:loopback:connected (externally):lo-id"
        self.assertEqual(hotspot.check("ap", 70), 70)
        self.assertEqual(nm.call_count, 1)
        self.assertEqual(hotspot.check("ap", 20), 100)
        nm.assert_called_with("-w", "30", "connection", "up", "uuid", "ap", "ifname", "wlan0", timeout=35)

    @patch("hotspot.nm")
    def test_does_not_disrupt_wifi_or_hotspot(self, nm):
        for ident in ("ap", "home"):
            nm.reset_mock()
            nm.return_value = "wlan0:wifi:connected:" + ident
            hotspot.check("ap", 0)
            self.assertEqual(nm.call_count, 1)

    @patch("hotspot.nm")
    def test_wired_lan_stops_hotspot(self, nm):
        nm.return_value = "wlan0:wifi:connected:ap\neth0:ethernet:connected:lan"
        hotspot.check("ap", 0)
        nm.assert_called_with("connection", "down", "uuid", "ap")

    def test_open_migration_preserves_address_and_identity(self):
        profile = {"802-11-wireless": {"mode": "ap", "security": "802-11-wireless-security"},
                   "802-11-wireless-security": {"key-mgmt": "wpa-psk"},
                   "connection": {"uuid": "same"}, "ipv4": {"method": "shared"}}
        self.assertTrue(make_open(profile))
        self.assertFalse(make_open(profile))
        self.assertEqual(profile, {"802-11-wireless": {"mode": "ap"},
                                   "connection": {"uuid": "same"}, "ipv4": {"method": "shared"}})

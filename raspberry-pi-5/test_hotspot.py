import unittest
from unittest.mock import patch

import hotspot
from provision import make_open


class HotspotTests(unittest.TestCase):
    @patch("hotspot.time.sleep")
    @patch("hotspot.nm")
    def test_offline_waits_then_activates(self, nm, sleep):
        nm.return_value = "wlan0:wifi:disconnected:\nlo:loopback:connected (externally):lo-id"
        hotspot.reconcile("ap")
        sleep.assert_called_once_with(hotspot.GRACE)
        self.assertEqual(nm.call_count, 3)
        nm.assert_called_with("-w", "30", "connection", "up", "uuid", "ap", "ifname", "wlan0", timeout=35)

    @patch("hotspot.time.sleep")
    @patch("hotspot.nm")
    def test_saved_wifi_returns_during_grace(self, nm, sleep):
        nm.side_effect = ["wlan0:wifi:disconnected:", "wlan0:wifi:connected:home"]
        hotspot.reconcile("ap")
        self.assertEqual(nm.call_count, 2)
        sleep.assert_called_once_with(hotspot.GRACE)

    @patch("hotspot.nm")
    def test_does_not_disrupt_wifi_or_hotspot(self, nm):
        for ident in ("ap", "home"):
            nm.reset_mock()
            nm.return_value = "wlan0:wifi:connected:" + ident
            hotspot.reconcile("ap")
            self.assertEqual(nm.call_count, 1)

    @patch("hotspot.nm")
    def test_wired_lan_stops_hotspot(self, nm):
        nm.return_value = "wlan0:wifi:connected:ap\neth0:ethernet:connected:lan"
        hotspot.reconcile("ap")
        nm.assert_called_with("connection", "down", "uuid", "ap")

    def test_open_migration_preserves_address_and_identity(self):
        profile = {"802-11-wireless": {"mode": "ap", "security": "802-11-wireless-security"},
                   "802-11-wireless-security": {"key-mgmt": "wpa-psk"},
                   "connection": {"uuid": "same"}, "ipv4": {"method": "shared"}}
        self.assertTrue(make_open(profile))
        self.assertFalse(make_open(profile))
        self.assertEqual(profile, {"802-11-wireless": {"mode": "ap"},
                                   "connection": {"uuid": "same"}, "ipv4": {"method": "shared"}})

"""Offline checks for network transitions and configuration-page requests."""
import io
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import network
from server import Handler


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.controller = network.Controller("ap-uuid")

    @patch("network.devices", return_value=[])
    @patch("network.nm")
    def test_fallback_waits_then_starts(self, nm, _):
        self.controller.monitor()
        nm.assert_not_called()
        self.controller.offline_since -= network.GRACE
        self.controller.monitor()
        self.assertIn("ap-uuid", nm.call_args.args)

    @patch("network.devices", return_value=[("wlan0", "wifi", "connected", "ap-uuid")])
    @patch("network.nm")
    def test_hotspot_remains_available(self, nm, _):
        self.controller.monitor()
        nm.assert_not_called()

    @patch("network.devices", return_value=[("eth0", "ethernet", "connected", "lan"),
                                           ("wlan0", "wifi", "connected", "ap-uuid")])
    @patch("network.nm", return_value="")
    def test_ethernet_replaces_hotspot(self, nm, _):
        self.controller.monitor()
        nm.assert_any_call("connection", "down", "uuid", "ap-uuid")

    @patch("network.devices", return_value=[("wlan0", "wifi", "connected", "ap-uuid")])
    @patch("network.nm")
    @patch("network.join", side_effect=subprocess.TimeoutExpired("nmcli", 45))
    def test_failed_join_restores_hotspot(self, join, nm, _):
        self.controller.change("join", "example", "test-pass")
        self.assertIn("Could not join", self.controller.notice)
        self.assertIn("ap-uuid", nm.call_args.args)

    @patch("network.dbus.SystemBus")
    @patch("network.dbus.Interface")
    @patch("network.nm")
    def test_profile_persistence(self, nm, interface, _):
        settings, trial = MagicMock(), MagicMock()
        settings.AddConnection2.return_value = ("/trial", {})
        interface.side_effect = [settings, trial, settings, trial]
        network.join("example", "test-pass")
        trial.Save.assert_called_once()
        nm.side_effect = subprocess.TimeoutExpired("nmcli", 45)
        with self.assertRaises(subprocess.TimeoutExpired):
            network.join("example", "wrong-pass")
        trial.Save.assert_called_once()
        trial.Delete.assert_called_once()


class PageTests(unittest.TestCase):
    def setUp(self):
        self.controller = network.Controller("ap")
        self.server = SimpleNamespace(authorization=b"Basic test", token="token",
                                      controller=self.controller, hotspot_name="Pi-Setup-test")

    def request(self, method="GET", path="/", auth=True, **fields):
        body = urlencode(fields).encode()
        headers = [f"{method} {path} HTTP/1.0", "Host: pi.local",
                   "Content-Type: application/x-www-form-urlencoded", f"Content-Length: {len(body)}"]
        if auth:
            headers.append("Authorization: Basic test")
        data = ("\r\n".join(headers) + "\r\n\r\n").encode() + body
        class InMemoryHandler(Handler):
            def setup(self):
                self.rfile = io.BytesIO(data)
                self.wfile = io.BytesIO()
            def finish(self):
                self.response = self.wfile.getvalue()
        return InMemoryHandler(None, ("localhost", 0), self.server).response

    def test_login_and_escaping(self):
        self.assertIn(b" 401 ", self.request(auth=False))
        self.controller.notice = "<unsafe>"
        page = self.request()
        self.assertIn(b" 200 ", page)
        self.assertIn(b"&lt;unsafe&gt;", page)
        self.assertIn(b"Pi-Setup-test", page)

    def test_form_protections_and_queue(self):
        fields = dict(token="token", ssid="travel", password="test-pass")
        self.assertIn(b" 401 ", self.request("POST", "/join", False, **fields))
        self.assertIn(b" 403 ", self.request("POST", "/join", token="wrong"))
        self.assertIn(b" 400 ", self.request("POST", "/join", token="token", ssid="travel"))
        self.assertIn(b" 202 ", self.request("POST", "/join", **fields))
        self.assertIn(b" 409 ", self.request("POST", "/retry", token="token"))
        self.assertEqual(self.controller.tasks.get_nowait(), ("join", "travel", "test-pass"))


if __name__ == "__main__":
    unittest.main()

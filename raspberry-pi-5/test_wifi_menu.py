import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import wifi_menu as wifi


# Run the actual detached shell jobs against a simulated radio. SSH disappearing
# must leave either the requested connection or the original hotspot active.
FAKE_NM = """#!/bin/sh
echo "$*" >> "$RUNTIME_DIRECTORY/calls"
case " $* " in
    *" GENERAL.CON-UUID "*) echo ap-uuid ;;
    *" 802-11-wireless.mode "*) echo ap ;;
    *" connection up uuid target "*) exit "${JOIN_STATUS:-0}" ;;
    *" device wifi list "*)
        echo '546573743A57:73:(none):pair_ccmp psk:WPA2'
        exit "${SCAN_STATUS:-0}" ;;
esac
"""


class HandoffTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.folder = Path(work.name)
        for name, script in (("nmcli", FAKE_NM), ("sleep", "#!/bin/sh\nexit 0\n")):
            path = self.folder / name
            path.write_text(script)
            path.chmod(0o755)

    def run_job(self, script, *args, **env):
        return subprocess.run(["/bin/sh", "-c", script, "pi-wifi", *args],
                              env={**os.environ, "PATH": f"{self.folder}:/usr/bin:/bin",
                                   "RUNTIME_DIRECTORY": str(self.folder), **env},
                              capture_output=True, text=True)

    def calls(self):
        return (self.folder / "calls").read_text()

    def test_new_profile_saved_after_join(self):
        result = self.run_job(wifi.HANDOFF, "target", "yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertLess(calls.index("connection down uuid ap-uuid"), calls.index("connection up uuid target"))
        self.assertLess(calls.index("connection up uuid target"), calls.index("connection modify uuid target"))
        self.assertNotIn("connection delete", calls)

    def test_wrong_password_restores_previous_and_discards_only_new_profile(self):
        for fresh in ("yes", "no"):
            with self.subTest(fresh=fresh):
                result = self.run_job(wifi.HANDOFF, "target", fresh, JOIN_STATUS="4")
                self.assertNotEqual(result.returncode, 0)
                calls = self.calls()
                self.assertTrue(calls.rstrip().endswith("connection up uuid ap-uuid ifname wlan0"))
                self.assertEqual("connection delete uuid target" in calls, fresh == "yes")
                self.assertNotIn("connection modify", calls)
                (self.folder / "calls").unlink()

    def test_scan_restores_hotspot_on_success_and_failure(self):
        for status in ("0", "1"):
            with self.subTest(status=status):
                result = self.run_job(wifi.SCAN_AND_RETURN, "ap-uuid", wifi.SCAN_FIELDS, SCAN_STATUS=status)
                self.assertEqual(result.returncode, int(status))
                self.assertTrue(self.calls().rstrip().endswith("connection up uuid ap-uuid ifname wlan0"))
                cache = self.folder / "nearby"
                self.assertEqual(cache.exists(), status == "0")
                if cache.exists():
                    self.assertEqual(wifi.scan_rows(cache.read_text()), {(b"Test:W", "wpa-psk"): 73})
                    cache.unlink()
                self.assertFalse(list(self.folder.glob("nearby.*")))


class MenuTests(unittest.TestCase):
    @patch("wifi_menu.subprocess.run")
    def test_hotspot_menu_includes_cached_scan_and_saved_networks(self, run):
        radio = wifi.Radio.__new__(wifi.Radio)
        radio.device = "/wifi"
        radio.settings = MagicMock()
        radio.settings.ListConnections.return_value = ["/ap", "/saved"]
        props = {wifi.NM + ".Device": {"ActiveConnection": "/active"},
                 wifi.NM + ".Device.Wireless": {"Mode": 3},
                 wifi.NM + ".Connection.Active": {"Id": "Setup profile", "Uuid": "ap-uuid"}}
        radio.properties = lambda path, name: props[name]

        def profile(path, unused):
            if path == "/ap":
                con, ssid, mode = {"id": "Setup profile", "uuid": "ap-uuid"}, b"Pi-Setup", "ap"
            else:
                con, ssid, mode = {"id": "Office profile", "uuid": "office"}, b"Office Wi-Fi", "infrastructure"
            obj = MagicMock()
            obj.GetSettings.return_value = {"connection": con, wifi.WIFI: {"ssid": ssid, "mode": mode}}
            return obj
        radio.interface = profile
        run.return_value = subprocess.CompletedProcess([], 0, stdout="50692D5365747570:80:(none):(none):\n")
        with TemporaryDirectory() as folder, patch.object(wifi, "CACHE", Path(folder) / "nearby"):
            wifi.CACHE.write_text("546573743A57:73:(none):psk:WPA2\n")
            rows, active, current, hotspot, age = radio.overview()
            self.assertEqual((active, current, hotspot), ("ap-uuid", "Pi-Setup", True))
            self.assertIsNotNone(age)
            self.assertEqual([(n.name, n.signal) for n in rows], [("Office Wi-Fi", None), ("Test:W", 73)])
            os.utime(wifi.CACHE, (1, 1))
            self.assertEqual([n.name for n in radio.overview()[0]], ["Office Wi-Fi"])

    def test_hex_ssids_security_and_deduplication(self):
        text = ("413A5C:32:(none):psk:WPA2\n413A5C:71:(none):psk:WPA2\n"
                "42:38:(none):802.1X:WPA2 802.1X\n43:34:(none):(none):\n"
                "44:77:(none):sae:WPA3\n:50:(none):psk:WPA2\n")
        self.assertEqual(wifi.scan_rows(text), {(b"A:\\", "wpa-psk"): 71, (b"B", "other"): 38,
                                               (b"C", "open"): 34, (b"D", "sae"): 77})
        self.assertNotIn("\x1b", wifi.Network(b"untrusted\x1b[2J", "open").name)

    @patch("wifi_menu.start_job", side_effect=subprocess.CalledProcessError(1, "systemd-run"))
    @patch("wifi_menu.getpass.getpass", return_value="example-test-pass")
    @patch("sys.stdin.isatty", return_value=True)
    def test_busy_unit_cleans_staged_profile_and_keeps_psk_out_of_job(self, isatty, password, start):
        radio = MagicMock()
        with self.assertRaises(subprocess.CalledProcessError):
            wifi.create_and_switch(radio, b"Sample", "wpa-psk", True)
        profile = radio.settings.AddConnectionUnsaved.call_args.args[0]
        self.assertEqual(bytes(profile[wifi.WIFI]["ssid"]), b"Sample")
        self.assertTrue(profile[wifi.WIFI]["hidden"])
        self.assertFalse(profile["connection"]["autoconnect"])
        self.assertEqual(profile[wifi.SEC]["psk"], "example-test-pass")
        start.assert_called_once_with(wifi.HANDOFF, profile["connection"]["uuid"], "yes")
        radio.interface.return_value.Delete.assert_called_once()

    @patch("wifi_menu.start_job")
    @patch("builtins.print")
    def test_same_network_and_declining_never_start_job(self, output, start):
        known = wifi.Network(b"Home", "wpa-psk", "saved-profile", "home-uuid")
        self.assertFalse(wifi.switch(known, "home-uuid"))
        with patch("builtins.input", return_value=""):
            self.assertFalse(wifi.switch(known, "ap-uuid"))
        start.assert_not_called()

    @patch("wifi_menu.start_job")
    @patch("builtins.print")
    @patch("wifi_menu.subprocess.run", return_value=subprocess.CompletedProcess([], 1, stdout=""))
    def test_paused_scan_requires_confirmation(self, cmd, output, start):
        radio = MagicMock()
        radio.properties.return_value = {"LastScan": -1}
        with patch("builtins.input", return_value=""):
            self.assertFalse(wifi.rescan(radio, True, "ap-uuid", "Pi-Setup"))
        start.assert_not_called()
        with patch("builtins.input", return_value="y"):
            self.assertTrue(wifi.rescan(radio, True, "ap-uuid", "Pi-Setup"))
        start.assert_called_once_with(wifi.SCAN_AND_RETURN, "ap-uuid", wifi.SCAN_FIELDS, saved_scan=True)


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import dbus
import provision


class ProfileTests(unittest.TestCase):
    def test_fresh_install_then_reinstall(self):
        # Model an empty NetworkManager settings database, retaining the actual D-Bus settings.
        profiles = {}
        settings = MagicMock()
        connection = MagicMock()

        def lookup(ident):
            if ident not in profiles:
                raise dbus.DBusException("Missing profile", name=provision.NM + ".Settings.InvalidConnection")
            return "/existing"

        def add(profile):
            profiles[profile["connection"]["uuid"]] = profile
            connection.GetSettings.return_value = profile

        settings.GetConnectionByUuid.side_effect = lookup
        settings.AddConnection.side_effect = add
        with TemporaryDirectory() as folder, \
             patch.object(provision, "CONFIG", Path(folder) / "config.json"), \
             patch("provision.socket.gethostname", return_value="field-unit.local"), \
             patch("provision.dbus.SystemBus"), patch("provision.os.chown"), \
             patch("provision.grp.getgrnam"), \
             patch("provision.dbus.Interface", side_effect=[settings, settings, connection]):
            provision.main()
            first = json.loads(provision.CONFIG.read_text())
            self.assertEqual(first["hotspot_ssid"], "Pi-Setup-field-unit")
            profile = profiles[first["hotspot_uuid"]]
            self.assertEqual(bytes(profile["802-11-wireless"]["ssid"]), b"Pi-Setup-field-unit")
            self.assertNotIn("802-11-wireless-security", profile)
            self.assertFalse(profile["connection"]["autoconnect"])
            provision.main()
            self.assertEqual(first, json.loads(provision.CONFIG.read_text()))
        settings.AddConnection.assert_called_once()
        connection.Update.assert_not_called()


if __name__ == "__main__":
    unittest.main()

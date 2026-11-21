"""Create the open hotspot or migrate an existing Pi setup hotspot in place."""
import grp
import json
import os
from pathlib import Path
import socket
import uuid

import dbus

NM = "org.freedesktop.NetworkManager"
BASE = "/org/freedesktop/NetworkManager"
CONFIG = Path("/etc/rpi-setup/config.json")


def make_open(profile):
    changed = profile.pop("802-11-wireless-security", None) is not None
    if profile["802-11-wireless"].pop("security", None) is not None:
        changed = True
    return changed


def main():
    existing = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    hostname = socket.gethostname().split(".")[0]
    config = {"hotspot_uuid": existing.get("hotspot_uuid") or str(uuid.uuid4()),
              "hotspot_ssid": existing.get("hotspot_ssid") or f"Pi-Setup-{hostname[:23]}"}
    # Record the identity before provisioning so interrupted installs can reuse it.
    temp = CONFIG.with_suffix(".tmp")
    temp.write_text(json.dumps(config, indent=2) + "\n")
    os.chown(temp, 0, grp.getgrnam("rpi-setup").gr_gid)
    temp.chmod(0o640)
    temp.replace(CONFIG)

    bus = dbus.SystemBus()
    settings = dbus.Interface(bus.get_object(NM, BASE + "/Settings"), NM + ".Settings")
    try:
        path = settings.GetConnectionByUuid(config["hotspot_uuid"])
    except dbus.DBusException as exc:
        if exc.get_dbus_name() != NM + ".Settings.InvalidConnection":
            raise
    else:
        connection = dbus.Interface(bus.get_object(NM, path), NM + ".Settings.Connection")
        profile = connection.GetSettings()
        if profile.get("802-11-wireless", {}).get("mode") != "ap":
            raise ValueError("The recorded hotspot UUID belongs to a different kind of profile.")
        if make_open(profile):
            connection.Update(profile)
        return

    settings.AddConnection({
        "connection": {"id": "Pi setup hotspot", "uuid": config["hotspot_uuid"],
                       "interface-name": "wlan0", "type": "802-11-wireless", "autoconnect": False},
        "802-11-wireless": {"ssid": dbus.ByteArray(config["hotspot_ssid"].encode()),
                            "mode": "ap", "band": "bg"},
        "ipv4": {"method": "shared", "address-data": dbus.Array([
            dbus.Dictionary({"address": "10.42.0.1", "prefix": dbus.UInt32(24)}, signature="sv")
        ], signature="a{sv}")},
        "ipv6": {"method": "disabled"},
    })


if __name__ == "__main__":
    main()

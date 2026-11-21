"""Run as root from install.sh. Keep per-device credentials outside the checkout."""
import grp
import json
import os
from pathlib import Path
import secrets
import socket
import uuid

import dbus

from network import BASE, IFACE, NM


def main():
    config_dir = Path("/etc/rpi-setup")
    config_path = config_dir / "config.json"
    if not config_path.exists():
        hostname = socket.gethostname().split(".")[0]
        config = {
            "hotspot_uuid": str(uuid.uuid4()),
            "hotspot_ssid": f"Pi-Setup-{hostname[:23]}",
            "hotspot_password": secrets.token_urlsafe(15),
            "admin_password": secrets.token_urlsafe(18),
        }
        temp = config_path.with_suffix(".tmp")
        temp.write_text(json.dumps(config, indent=2) + "\n")
        os.chown(temp, 0, grp.getgrnam("rpi-setup").gr_gid)
        temp.chmod(0o640)
        temp.replace(config_path)

    config = json.loads(config_path.read_text())
    bus = dbus.SystemBus()
    settings = dbus.Interface(bus.get_object(NM, BASE + "/Settings"), NM + ".Settings")
    try:
        settings.GetConnectionByUuid(config["hotspot_uuid"])
        return
    except dbus.DBusException as exc:
        if exc.get_dbus_name() != NM + ".Settings.InvalidConnection":
            raise
    settings.AddConnection({
        "connection": {"id": "Pi setup hotspot", "uuid": config["hotspot_uuid"],
                       "interface-name": IFACE, "type": "802-11-wireless", "autoconnect": False},
        "802-11-wireless": {"ssid": dbus.ByteArray(config["hotspot_ssid"].encode()),
                            "mode": "ap", "band": "bg"},
        "802-11-wireless-security": {"key-mgmt": "wpa-psk", "psk": config["hotspot_password"]},
        "ipv4": {"method": "shared", "address-data": dbus.Array([
            dbus.Dictionary({"address": "10.42.0.1", "prefix": dbus.UInt32(24)}, signature="sv")
        ], signature="a{sv}")},
        "ipv6": {"method": "disabled"},
    })


if __name__ == "__main__":
    main()

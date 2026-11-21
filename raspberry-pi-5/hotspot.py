"""Keep a fallback hotspot available when the Pi has no active LAN."""
import json
import os
from pathlib import Path
import subprocess
import time

CONFIG = Path("/etc/rpi-setup/config.json")
GRACE = 60


def nm(*args, timeout=12):
    return subprocess.run(["/usr/bin/nmcli", "--colors", "no", *args],
                          capture_output=True, text=True, timeout=timeout, check=True,
                          env={**os.environ, "LC_ALL": "C"}).stdout.strip()


def connections(hotspot):
    rows = nm("-t", "--escape", "no", "-f", "DEVICE,TYPE,STATE,CON-UUID",
              "device", "status").splitlines()
    active = [row.split(":", 3) for row in rows]
    lan = False
    ap = False
    for _, kind, state, ident in active:
        if kind in ("ethernet", "wifi") and state.startswith("connected"):
            if ident == hotspot:
                ap = True
            else:
                lan = True
    return lan, ap


def reconcile(hotspot):
    lan, ap = connections(hotspot)
    if not (lan or ap):
        # Give saved profiles a chance to connect, then reread the live state.
        time.sleep(GRACE)
        lan, ap = connections(hotspot)
    if lan and ap:
        nm("connection", "down", "uuid", hotspot)
    elif not (lan or ap):
        nm("-w", "30", "connection", "up", "uuid", hotspot, "ifname", "wlan0", timeout=35)


if __name__ == "__main__":
    reconcile(json.loads(CONFIG.read_text())["hotspot_uuid"])

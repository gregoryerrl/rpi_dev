"""Keep a fallback hotspot available when the Pi has no active LAN."""
import json
import logging
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


def check(hotspot, last_online):
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
    now = time.monotonic()
    if lan and ap:
        nm("connection", "down", "uuid", hotspot)
    if lan or ap:
        return now
    if now - last_online >= GRACE:
        nm("-w", "30", "connection", "up", "uuid", hotspot, "ifname", "wlan0", timeout=35)
        return now
    return last_online


def main():
    hotspot = json.loads(CONFIG.read_text())["hotspot_uuid"]
    last_online = time.monotonic()
    while True:
        try:
            last_online = check(hotspot, last_online)
        except (subprocess.SubprocessError, OSError) as exc:
            logging.warning("NetworkManager check failed: %s", getattr(exc, "stderr", None) or exc)
        time.sleep(5)


if __name__ == "__main__":
    main()

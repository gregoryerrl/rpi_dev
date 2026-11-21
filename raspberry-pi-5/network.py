"""NetworkManager operations for the setup page. All changes run on one worker."""
import logging
import os
import queue
import re
import subprocess
import threading
import time
import uuid

import dbus

NM = "org.freedesktop.NetworkManager"
BASE = "/org/freedesktop/NetworkManager"
IFACE = "wlan0"
GRACE = 60


def nm(*args, timeout=12):
    result = subprocess.run(["/usr/bin/nmcli", "--colors", "no", *args],
                            capture_output=True, text=True, timeout=timeout,
                            env={**os.environ, "LC_ALL": "C"}, check=True)
    return result.stdout.strip()


def devices():
    output = nm("-t", "--escape", "no", "-f", "DEVICE,TYPE,STATE,CON-UUID",
                "device", "status")
    return [line.split(":", 3) for line in output.splitlines()]


def validate(ssid, password):
    if not 1 <= len(ssid.encode()) <= 32 or any(ord(c) < 32 for c in ssid):
        raise ValueError("Enter a Wi-Fi name between 1 and 32 bytes.")
    if not (8 <= len(password) <= 63 and all(32 <= ord(c) <= 126 for c in password)
            or re.fullmatch("[0-9a-fA-F]{64}", password)):
        raise ValueError("Enter an 8–63 character Wi-Fi password or a 64-digit hex key.")


def join(ssid, password):
    """Trial an in-memory WPA-Personal profile. Persist only after activation."""
    bus = dbus.SystemBus()
    settings = dbus.Interface(bus.get_object(NM, BASE + "/Settings"), NM + ".Settings")
    ident = str(uuid.uuid4())
    profile = {
        "connection": {"type": "802-11-wireless", "id": ssid, "uuid": ident,
                       "interface-name": IFACE, "autoconnect": dbus.Boolean(True)},
        "802-11-wireless": {"ssid": dbus.ByteArray(ssid.encode()), "mode": "infrastructure"},
        "802-11-wireless-security": {"key-mgmt": "wpa-psk", "psk": password},
        "user": {"data": dbus.Dictionary({"dev.rpi-setup.owner": "setup-page"}, signature="ss")},
        "ipv4": {"method": "auto"}, "ipv6": {"method": "auto"},
    }
    path, _ = settings.AddConnection2(profile, dbus.UInt32(0x02 | 0x20), {})
    connection = dbus.Interface(bus.get_object(NM, path), NM + ".Settings.Connection")
    try:
        nm("-w", "45", "connection", "up", "uuid", ident, "ifname", IFACE, timeout=50)
        connection.Save()
    except Exception:
        connection.Delete()
        raise

    # Retire only this tool's older profiles for the same SSID after a successful save.
    for old_path in settings.ListConnections():
        if old_path == path:
            continue
        old = dbus.Interface(bus.get_object(NM, old_path), NM + ".Settings.Connection")
        try:
            props = old.GetSettings()
            owner = props.get("user", {}).get("data", {}).get("dev.rpi-setup.owner")
            if owner == "setup-page" and bytes(props.get("802-11-wireless", {}).get("ssid", [])) == ssid.encode():
                old.Delete()
        except dbus.DBusException:
            logging.warning("Could not inspect or retire an older Wi-Fi profile")


class Controller:
    def __init__(self, hotspot):
        self.hotspot = hotspot
        self.tasks = queue.Queue(maxsize=1)
        self.busy = threading.Lock()
        self.status = "Checking network connections…"
        self.details = ""
        self.notice = ""
        self.offline_since = time.monotonic()

    def submit(self, action, ssid="", password=""):
        if not self.busy.acquire(blocking=False):
            return False
        self.tasks.put_nowait((action, ssid, password))
        return True

    def activate(self, ident):
        nm("-w", "30", "connection", "up", "uuid", ident, "ifname", IFACE, timeout=35)

    def monitor(self):
        rows = devices()
        connected = [r for r in rows if r[2].startswith("connected")]
        uplinks = [r for r in connected if r[1] in ("wifi", "ethernet") and r[3] != self.hotspot]
        ap = any(r[3] == self.hotspot for r in connected)
        now = time.monotonic()
        self.details = ""
        if uplinks:
            self.status = "Connected via " + ", ".join(r[0] for r in uplinks)
            self.offline_since = now
            if ap:
                nm("connection", "down", "uuid", self.hotspot)
            addresses = []
            for device, _, _, _ in uplinks:
                profile = nm("-g", "GENERAL.CONNECTION", "--escape", "no", "device", "show", device)
                ips = nm("-g", "IP4.ADDRESS", "device", "show", device)
                addresses.extend(f"{profile} · https://{ip.split('/')[0]}:8443" for ip in ips.splitlines())
            self.details = " | ".join(addresses)
        elif ap:
            self.status = "Setup hotspot active"
            self.offline_since = now
        elif now - self.offline_since >= GRACE:
            self.status = "Starting the setup hotspot…"
            self.activate(self.hotspot)
            self.offline_since = now
        else:
            self.status = "Waiting for a saved network…"

    def change(self, action, ssid, password):
        previous = next((r[3] for r in devices() if r[0] == IFACE
                         and r[2].startswith("connected")), None)
        if action == "retry":
            if previous == self.hotspot:
                nm("connection", "down", "uuid", self.hotspot)
                nm("device", "set", IFACE, "autoconnect", "yes")
            self.notice = "Saved Wi-Fi profiles can now reconnect."
            self.offline_since = time.monotonic()
            return
        try:
            if previous == self.hotspot:
                nm("connection", "down", "uuid", self.hotspot)
                nm("-g", "SSID", "device", "wifi", "list", "ifname", IFACE, "--rescan", "yes", timeout=20)
            join(ssid, password)
            self.notice = "Connected to " + ssid + "."
        except Exception:
            self.notice = "Could not join that network. Check the name and password."
            self.offline_since = time.monotonic() - GRACE
            if previous:
                self.activate(previous)

    def run(self):
        while True:
            try:
                self.monitor()
            except (subprocess.SubprocessError, OSError):
                self.status = "Waiting for NetworkManager…"
                logging.warning("Network status check or hotspot activation failed")
            try:
                task = self.tasks.get(timeout=5)
            except queue.Empty:
                continue
            try:
                time.sleep(2)  # Allow the browser to receive the response before changing radio mode.
                self.change(*task)
            except Exception as exc:
                logging.warning("Network change failed (%s)", type(exc).__name__)
                self.notice = "Network change failed. Checking available connections."
            finally:
                del task
                self.busy.release()

#!/usr/bin/python3 -I
"""Choose a Wi-Fi network over SSH on a Pi with a fallback hotspot."""
import argparse
from dataclasses import dataclass, replace
import getpass
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

import dbus

NM = "org.freedesktop.NetworkManager"
BASE = "/org/freedesktop/NetworkManager"
WIFI = "802-11-wireless"
SEC = "802-11-wireless-security"
IFACE = "wlan0"
SCAN_FIELDS = "SSID-HEX,SIGNAL,WPA-FLAGS,RSN-FLAGS,SECURITY"
CACHE = Path("/run/pi-wifi/nearby")
SECURITY = {"wpa-psk": "WPA personal", "sae": "WPA3 personal", "open": "Open",
            "owe": "Enhanced Open", "other": "Other security"}
KEY_MANAGEMENT = {"psk": "wpa-psk", "sae": "sae", "owe": "owe", "owe_tm": "owe"}


def printable(value):
    return "".join(c if c.isprintable() else ascii(c)[1:-1] for c in str(value))


@dataclass(frozen=True)
class Network:
    ssid: bytes
    security: str
    profile: str = ""
    uuid: str = ""
    signal: int | None = None

    @property
    def name(self):
        return printable(self.ssid.decode("utf-8", errors="backslashreplace"))


def scan_rows(output):
    nearby = {}
    for row in output.splitlines():
        try:
            encoded, signal, wpa, rsn, security = row.split(":", 4)
            ssid = bytes.fromhex(encoded)
            strength = int(signal)
        except ValueError:
            continue
        if not any(ssid) or len(ssid) > 32:
            continue
        flags = (wpa + " " + rsn).lower().split()
        kind = next((label for flag, label in KEY_MANAGEMENT.items() if flag in flags), None)
        key = (ssid, kind or ("open" if security in ("", "--") else "other"))
        nearby[key] = max(strength, nearby.get(key, 0))
    return nearby


def scan_command(rescan):
    return ["/usr/bin/nmcli", "--colors", "no", "-t", "-e", "no", "-w", "12", "-f", SCAN_FIELDS,
            "device", "wifi", "list", "ifname", IFACE, "--rescan", rescan]


class Radio:
    def __init__(self):
        self.bus = dbus.SystemBus()
        self.settings = self.interface(BASE + "/Settings", NM + ".Settings")
        self.device = self.interface(BASE, NM).GetDeviceByIpIface(IFACE)

    def interface(self, path, name):
        return dbus.Interface(self.bus.get_object(NM, path), name)

    def properties(self, path, name):
        return self.interface(path, dbus.PROPERTIES_IFACE).GetAll(name)

    def overview(self):
        device = self.properties(self.device, NM + ".Device")
        wireless = self.properties(self.device, NM + ".Device.Wireless")
        current = {}
        if device["ActiveConnection"] != "/":
            current = self.properties(device["ActiveConnection"], NM + ".Connection.Active")
        active = str(current.get("Uuid", ""))
        current_name = str(current.get("Id", ""))
        hotspot = int(wireless["Mode"]) == 3
        saved, own_ssids = [], set()
        for path in self.settings.ListConnections():
            try:
                profile = self.interface(path, NM + ".Settings.Connection").GetSettings()
            except dbus.DBusException as exc:
                if exc.get_dbus_name() in (NM + ".Settings.PermissionDenied", "org.freedesktop.DBus.Error.UnknownObject"):
                    continue
                raise
            if WIFI not in profile:
                continue
            wifi, con = profile[WIFI], profile["connection"]
            ssid = bytes(wifi["ssid"])
            if wifi.get("mode") == "ap":
                own_ssids.add(ssid)
                if con["uuid"] == active:
                    current_name = Network(ssid, "open").name
            elif wifi.get("mode", "infrastructure") == "infrastructure" and con.get("interface-name", IFACE) == IFACE:
                security = str(profile.get(SEC, {}).get("key-mgmt", "open"))
                saved.append(Network(ssid, security if security in SECURITY else "other",
                                     str(con["id"]), str(con["uuid"])))
        nearby, age = {}, None
        if hotspot:
            try:
                with CACHE.open() as f:
                    seconds = int(time.time() - os.fstat(f.fileno()).st_mtime)
                    if 0 <= seconds <= 300:
                        nearby.update(scan_rows(f.read()))
                        age = seconds
            except FileNotFoundError:
                pass
        scan = subprocess.run(scan_command("no"), capture_output=True, text=True,
                              env={**os.environ, "LC_ALL": "C"})
        if scan.returncode == 0:
            nearby.update(scan_rows(scan.stdout))
        rows = [replace(n, signal=nearby.get((n.ssid, n.security))) for n in saved]
        saved_keys = {(n.ssid, n.security) for n in saved}
        rows.extend(Network(ssid, sec, signal=signal) for (ssid, sec), signal in nearby.items()
                    if (ssid, sec) not in saved_keys and ssid not in own_ssids)
        rows.sort(key=lambda n: (not (n.uuid and n.uuid == active), not bool(n.uuid), -(n.signal or 0),
                                 n.name.casefold(), n.profile, n.uuid))
        return rows, active, current_name, hotspot, age


# Only the system shell and UUIDs cross the SSH disconnect. No credentials are
# included in the transient unit. One named unit serializes competing handoffs.
HANDOFF = r"""
target=$1
fresh=$2
previous=$(nmcli -g GENERAL.CON-UUID device show wlan0)
if [ "$previous" = "--" ]; then previous=; fi
if [ "$previous" = "$target" ]; then
    if [ "$fresh" = yes ]; then nmcli connection modify uuid "$target" connection.autoconnect yes; fi
    exit $?
fi
mode=
if [ -n "$previous" ]; then
    mode=$(nmcli -g 802-11-wireless.mode connection show uuid "$previous")
fi
activate() {
    if [ "$mode" = ap ]; then
        nmcli -w 10 connection down uuid "$previous" || return 1
    fi
    nmcli -w 8 -g SSID device wifi list ifname wlan0 --rescan yes >/dev/null || :
    nmcli -w 35 connection up uuid "$target" ifname wlan0 || return 1
    if [ "$fresh" = yes ]; then
        nmcli connection modify uuid "$target" connection.autoconnect yes || return 1
    fi
}
if activate; then exit 0; fi
if [ "$fresh" = yes ]; then nmcli connection delete uuid "$target" || :; fi
if [ -n "$previous" ]; then
    nmcli -w 20 connection up uuid "$previous" ifname wlan0 || :
fi
exit 1
"""

SCAN_AND_RETURN = r"""
set -eu
previous=$1
[ "$(nmcli -g GENERAL.CON-UUID device show wlan0)" = "$previous" ]
[ "$(nmcli -g 802-11-wireless.mode connection show uuid "$previous")" = ap ]
temp=$(mktemp "$RUNTIME_DIRECTORY/nearby.XXXXXX")
restore() {
    rm -f -- "$temp"
    nmcli -w 25 connection up uuid "$previous" ifname wlan0
}
trap restore EXIT
nmcli -w 10 connection down uuid "$previous"
for delay in 0 2 3; do
    sleep "$delay"
    if nmcli --colors no -t -e no -w 12 -f "$2" device wifi list ifname wlan0 --rescan yes >"$temp" &&
       { [ -s "$temp" ] || [ "$delay" = 3 ]; }; then
        chmod 644 "$temp"
        mv -f -- "$temp" "$RUNTIME_DIRECTORY/nearby"
        exit 0
    fi
done
exit 1
"""


def privileged(command):
    return command if os.geteuid() == 0 else ["/usr/bin/sudo", "--", *command]


def start_job(script, *args, saved_scan=False):
    command = ["/usr/bin/systemd-run", "--collect", "--no-block", "--unit=rpi-wifi-return",
               "--expand-environment=no", "--setenv=LC_ALL=C"]
    if saved_scan:
        command += ["-p", "RuntimeDirectory=pi-wifi", "-p", "RuntimeDirectoryPreserve=yes"]
    subprocess.run(privileged([*command, "/bin/sh", "-c", script, "pi-wifi", *args]), check=True)


def rescan(radio, hotspot, active, current):
    scan = subprocess.run(privileged(scan_command("yes")), stdout=subprocess.PIPE, text=True,
                          env={**os.environ, "LC_ALL": "C"})
    wireless = radio.properties(radio.device, NM + ".Device.Wireless")
    age = time.clock_gettime(time.CLOCK_BOOTTIME) - int(wireless["LastScan"]) / 1000
    visible = [Network(ssid, sec).name for ssid, sec in scan_rows(scan.stdout)]
    if scan.returncode == 0 and 0 <= age < 15 and (not hotspot or any(n != current for n in visible)):
        return False
    if not hotspot:
        print("Fresh scan unavailable. Choose a saved network or enter its name.")
        return False
    print("A fresh scan needs to pause the hotspot. It will come back after the scan.")
    if input("Pause the hotspot and scan? [y/N] ").strip().lower() not in ("yes", "y"):
        return False
    print(f"Rejoin {printable(current)}, SSH to 10.42.0.1 and run pi-wifi again to see the results.", flush=True)
    start_job(SCAN_AND_RETURN, active, SCAN_FIELDS, saved_scan=True)
    return True


def create_and_switch(radio, ssid, security, hidden):
    name = Network(ssid, security).name
    ident = str(uuid.uuid4())
    profile = {
        "connection": {"id": name, "uuid": ident, "type": WIFI, "interface-name": IFACE,
                       "autoconnect": dbus.Boolean(False)},
        WIFI: {"ssid": dbus.ByteArray(ssid), "mode": "infrastructure", "hidden": dbus.Boolean(hidden)},
        "ipv4": {"method": "auto"}, "ipv6": {"method": "auto"},
    }
    if security != "open":
        profile[SEC] = {"key-mgmt": security}
        if security in ("wpa-psk", "sae"):
            if not sys.stdin.isatty():
                raise ValueError("Open an interactive SSH terminal to enter the Wi-Fi password.")
            try:
                password = getpass.getpass(f"Wi-Fi password for {name}: ")
            except (EOFError, KeyboardInterrupt):
                raise ValueError("Cancelled Wi-Fi password entry.") from None
            if not password:
                raise ValueError("A Wi-Fi password is required.")
            profile[SEC]["psk"] = password
    # Keep untested credentials out of autoconnect and off disk until the join succeeds.
    path = radio.settings.AddConnectionUnsaved(profile)
    try:
        start_job(HANDOFF, ident, "yes")
    except (OSError, subprocess.CalledProcessError):
        radio.interface(path, NM + ".Settings.Connection").Delete()
        raise


def show(rows, active, current_name, hotspot, age):
    current = next((n.name for n in rows if n.uuid and n.uuid == active), printable(current_name))
    print("\nPi Wi-Fi")
    print("Current ·", ("Hotspot (" + current + ")") if hotspot else current or "Offline")
    if not rows:
        print("No saved or nearby networks found.")
    for i, n in enumerate(rows, 1):
        details = []
        if n.uuid:
            details.append("connected" if n.uuid == active else "saved")
        if n.profile and n.profile != n.name:
            details.append(printable(n.profile))
        if n.signal is not None:
            details.append(f"{n.signal}% signal")
        details.append(SECURITY.get(n.security, "Other security"))
        print(f" {i:2}. {n.name}  ·  {' / '.join(details)}")
    if hotspot:
        if age is not None:
            print(f"Hotspot scan from {age} seconds ago.")
        else:
            print("Hotspot mode can limit scans. Use r for a fresh list or a to enter a name.")


def manual():
    name = input("Network name (SSID, blank to cancel): ")
    if not name:
        return None
    ssid = name.encode()
    if len(ssid) > 32:
        raise ValueError("The network name must fit in 32 bytes.")
    print(" 1. WPA/WPA2 personal    2. WPA3 personal    3. Open    4. Enhanced Open")
    choice = input("Security [1]: ").strip() or "1"
    security = {"1": "wpa-psk", "2": "sae", "3": "open", "4": "owe"}.get(choice)
    if not security:
        raise ValueError("Choose one of the listed security types.")
    hidden = input("Is the SSID hidden? [y/N] ").strip().lower() in ("y", "yes")
    return Network(ssid, security), hidden


def switch(network, active, hidden=False, confirm=True, hotspot_name=None):
    if network.uuid and network.uuid == active:
        print(f"Already connected to {network.name}.")
        return False
    if not network.uuid and network.security not in ("open", "wpa-psk", "sae", "owe"):
        print("Set up this network with nmtui-edit first, then choose its saved profile.")
        return False
    if confirm and input(f"Switch to {network.name}? Wi-Fi SSH will disconnect. [y/N] ").strip().lower() not in ("y", "yes"):
        return False
    host = socket.gethostname().split(".")[0]
    user = os.environ.get("SUDO_USER") or getpass.getuser()
    print(f"Join {network.name} on your laptop, then use ssh {user}@{host}.local.")
    if hotspot_name:
        print(f"If the join fails, rejoin {printable(hotspot_name)} and use ssh {user}@10.42.0.1.", flush=True)
    else:
        print("If the join fails, reconnect on your previous network.", flush=True)
    if network.uuid:
        start_job(HANDOFF, network.uuid, "no")
    else:
        command = ["/usr/bin/python3", "-I", str(Path(__file__).resolve()), "--add",
                   network.ssid.hex(), network.security, "hidden" if hidden else "visible"]
        subprocess.run(privileged(command), check=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="show saved networks and the latest scan")
    mode.add_argument("--profile", metavar="NAME", help="switch directly to a saved profile")
    mode.add_argument("--add", nargs=3, help=argparse.SUPPRESS)
    args = parser.parse_args()
    radio = Radio()
    if args.add:
        encoded, security, visibility = args.add
        ssid = bytes.fromhex(encoded)
        if (os.geteuid() != 0 or not 1 <= len(ssid) <= 32
                or security not in ("open", "wpa-psk", "sae", "owe") or visibility not in ("hidden", "visible")):
            raise ValueError("Invalid new Wi-Fi profile request.")
        create_and_switch(radio, ssid, security, visibility == "hidden")
        return
    while True:
        rows, active, name, hotspot, age = radio.overview()
        if args.profile is not None:
            matches = [n for n in rows if n.uuid and n.profile == args.profile]
            if len(matches) != 1:
                raise ValueError("Choose a saved Wi-Fi profile from the pi-wifi menu.")
            switch(matches[0], active, confirm=False, hotspot_name=name if hotspot else None)
            return
        show(rows, active, name, hotspot, age)
        if args.list:
            return
        choice = input("\nNetwork number, [r] rescan, [a] enter SSID, [q] quit: ").strip().lower()
        if choice == "q":
            return
        if choice == "r":
            if rescan(radio, hotspot, active, name):
                return
            continue
        try:
            if choice == "a":
                selection = manual()
                if selection is None:
                    continue
                target, hidden = selection
                matches = [n for n in rows if n.uuid and n.ssid == target.ssid and n.security == target.security]
                if len(matches) > 1:
                    print("Several saved profiles match. Choose one by number.")
                    continue
                if matches:
                    target = matches[0]
            elif choice.isascii() and choice.isdigit() and 1 <= int(choice) <= len(rows):
                target, hidden = rows[int(choice) - 1], False
            else:
                print("Choose a listed number, r, a, or q.")
                continue
            if switch(target, active, hidden, hotspot_name=name if hotspot else None):
                return
        except (ValueError, subprocess.CalledProcessError) as exc:
            print(str(exc) if isinstance(exc, ValueError) else "The switch could not be scheduled.", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
    except (dbus.DBusException, OSError, ValueError) as error:
        sys.exit(printable(error))
    except subprocess.CalledProcessError:
        sys.exit(1)

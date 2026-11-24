#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if (( EUID != 0 )); then
    echo "Run sudo ./install.sh on the Pi." >&2
    exit 1
fi
umask 077
for tool in nmcli dnsmasq sshd; do
    command -v "$tool" >/dev/null || { echo "Missing $tool. See README.md for dependencies." >&2; exit 1; }
done
/usr/bin/python3 -c 'import dbus'
systemctl is-active --quiet NetworkManager
if ! LC_ALL=C nmcli -g WIFI-PROPERTIES.AP device show wlan0 | grep -qx yes; then
    echo "The built-in wlan0 interface must be managed by NetworkManager and support hotspot mode." >&2
    exit 1
fi
exec 9>/run/lock/rpi-setup-install.lock
flock 9
id rpi-setup >/dev/null 2>&1 || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin rpi-setup
app=/usr/local/lib/rpi-setup
install -d -m 755 "$app"
install -d -m 750 -g rpi-setup /etc/rpi-setup
install -m 644 hotspot.py provision.py "$app/"
install -D -m 755 wifi_menu.py /usr/local/bin/pi-wifi
install -m 755 pi-wifi-return /usr/local/sbin/
systemctl enable --now ssh.service
/usr/bin/python3 -B "$app/provision.py"
# polkit watches this directory. Publish a complete, readable rule in one rename.
rules=/etc/polkit-1/rules.d
if ! cmp -s 60-rpi-setup.rules "$rules/60-rpi-setup.rules"; then
    rule_tmp=$(mktemp "$rules/.rpi-setup.XXXXXXXX")
    trap 'rm -f -- "$rule_tmp"' EXIT
    install -m 644 60-rpi-setup.rules "$rule_tmp"
    mv -fT "$rule_tmp" "$rules/60-rpi-setup.rules"
fi
install -m 644 rpi-setup.service /etc/systemd/system/
install -D -m 755 90-rpi-setup /etc/NetworkManager/dispatcher.d/90-rpi-setup
systemctl daemon-reload
systemctl enable rpi-setup.service
systemctl restart rpi-setup.service
systemctl is-active --quiet rpi-setup.service
systemctl is-active --quiet ssh.service
echo "SSH fallback hotspot installed. Hotspot SSH address: 10.42.0.1"
echo "Run pi-wifi over SSH to choose a network."
echo "If upgrading on the hotspot, its new security setting takes effect at the next activation."

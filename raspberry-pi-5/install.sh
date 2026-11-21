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
nmcli -g GENERAL.TYPE device show wlan0 | grep -qx wifi
exec 9>/run/lock/rpi-setup-install.lock
flock 9
id rpi-setup >/dev/null 2>&1 || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin rpi-setup
app=/usr/local/lib/rpi-setup
install -d -m 755 "$app"
install -d -m 750 -g rpi-setup /etc/rpi-setup
install -m 644 hotspot.py provision.py "$app/"
install -m 755 pi-wifi-return /usr/local/sbin/
systemctl enable --now ssh.service
/usr/bin/python3 -B "$app/provision.py"
install -m 644 60-rpi-setup.rules /etc/polkit-1/rules.d/
install -m 644 rpi-setup.service /etc/systemd/system/
install -D -m 755 90-rpi-setup /etc/NetworkManager/dispatcher.d/90-rpi-setup
systemctl daemon-reload
systemctl enable rpi-setup.service
systemctl restart rpi-setup.service
systemctl is-active --quiet rpi-setup.service ssh.service
echo "SSH fallback hotspot installed. Hotspot SSH address: 10.42.0.1"
echo "If upgrading on the hotspot, its new security setting takes effect at the next activation."

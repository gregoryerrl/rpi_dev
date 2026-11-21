#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if (( EUID != 0 )); then
    echo "Run sudo ./install.sh on the Pi." >&2
    exit 1
fi
umask 077
for tool in nmcli dnsmasq openssl avahi-daemon; do
    command -v "$tool" >/dev/null || { echo "Missing $tool. See README.md for dependencies." >&2; exit 1; }
done
/usr/bin/python3 -c 'import dbus'
systemctl is-active --quiet NetworkManager || { echo "Start NetworkManager before installing." >&2; exit 1; }
nmcli -g GENERAL.TYPE device show wlan0 | grep -qx wifi || { echo "A NetworkManager Wi-Fi interface named wlan0 is required." >&2; exit 1; }
exec 9>/run/lock/rpi-setup-install.lock
flock 9
id rpi-setup >/dev/null 2>&1 || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin rpi-setup
app=/usr/local/lib/rpi-setup
conf=/etc/rpi-setup
install -d -m 755 "$app"
install -d -m 750 -g rpi-setup "$conf"
install -m 644 network.py server.py page.html provision.py "$app/"
/usr/bin/python3 -B "$app/provision.py"
host=$(hostname -s)
if [[ ! -s "$conf/key.pem" || ! -s "$conf/cert.pem" ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=$host.local" \
        -addext "subjectAltName=DNS:$host.local,DNS:$host,IP:10.42.0.1" \
        -keyout "$conf/key.new" -out "$conf/cert.new"
    install -m 640 -g rpi-setup "$conf/key.new" "$conf/key.pem"
    install -m 644 "$conf/cert.new" "$conf/cert.pem"
    rm "$conf/key.new" "$conf/cert.new"
fi
install -m 644 60-rpi-setup.rules /etc/polkit-1/rules.d/
install -m 644 rpi-setup.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now avahi-daemon
systemctl enable rpi-setup.service
systemctl restart rpi-setup.service
/usr/bin/python3 - "$conf/config.json" <<'PY'
import http.client
import json
import socket
import ssl
import sys
import time

context = ssl.create_default_context(cafile="/etc/rpi-setup/cert.pem")
host = socket.gethostname().split(".")[0] + ".local"
for attempt in range(10):
    try:
        with socket.create_connection(("127.0.0.1", 8443), timeout=2) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                tls.sendall(b"GET / HTTP/1.0\r\n\r\n")
                response = http.client.HTTPResponse(tls)
                response.begin()
                if response.status != 401:
                    raise RuntimeError("Unexpected response from setup page")
        break
    except OSError:
        if attempt == 9:
            raise
        time.sleep(1)
with open(sys.argv[1]) as source:
    c = json.load(source)
print(f"LAN page: https://{host}:8443")
print(f"Hotspot: {c['hotspot_ssid']}  Password: {c['hotspot_password']}")
print("Hotspot page: https://10.42.0.1:8443")
print(f"Page login: admin  Password: {c['admin_password']}")
PY
openssl x509 -in "$conf/cert.pem" -noout -sha256 -fingerprint

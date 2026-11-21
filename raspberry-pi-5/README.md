# Raspberry Pi 5 Wi-Fi setup

A local HTTPS page for a Raspberry Pi 5 Model B running Debian Trixie or Raspberry Pi OS Trixie, with NetworkManager managing the built-in Wi-Fi interface, `wlan0`. The page runs from systemd at boot. It uses the system Python, python-dbus, and NetworkManager.

## Install on a Pi

From the checkout, run these commands in a terminal on the Pi. Already provisioned Wi-Fi profiles, including the home network, are preserved.

```sh
cd ~/rpi_dev/raspberry-pi-5
sudo ./install.sh
```

The installer prints the URLs, device-specific hotspot password, admin password, and TLS certificate fingerprint. Keep those somewhere accessible before leaving home. If installing on a minimal image, the required Debian packages are `network-manager python3-dbus dnsmasq-base openssl avahi-daemon polkitd`. NetworkManager must already manage the radio. Set the wireless country in the Pi's system settings if Wi-Fi is blocked on a fresh image.

## Open the page

- **On a LAN** — Join the same Wi-Fi or Ethernet LAN as the Pi and open `https://<hostname>.local:8443/`. If your device cannot resolve local names, use the Pi's IPv4 address from the router or `hostname -I`. Guest network client isolation can block device-to-device access.
- **Away from a LAN** — Give the Pi about a minute to try its saved networks. Join the printed `Pi-Setup-…` network, choose to stay connected if your phone reports no internet, then open `https://10.42.0.1:8443/`.
- **First visit** — The Pi generates its own TLS certificate. Compare the browser's SHA-256 certificate fingerprint with the installer output before accepting it. Sign in as `admin` with the printed page password. A new address may prompt for sign-in again.

Enter the name and password of a WPA/WPA2 personal network, then select **Save and connect**. The Pi's one radio switches networks, which briefly disconnects a hotspot client. Join the new LAN and open the hostname URL again. The Pi saves the profile after successful activation. If the join fails, it tries to restore the previous connection and falls back to its setup hotspot if offline.

The hotspot stays available while you use it. When returning home, **Retry saved Wi-Fi** releases the radio to NetworkManager for about a minute. Rebooting also gives saved networks the first opportunity. Plugging into a connected Ethernet LAN turns the fallback hotspot off. LAN access works without an internet connection.

## Operations

```sh
systemctl status rpi-setup
journalctl -u rpi-setup -b
sudo cat /etc/rpi-setup/config.json
sudo openssl x509 -in /etc/rpi-setup/cert.pem -noout -sha256 -fingerprint
```

The JSON file contains both device passwords. Keep it private. The service runs as the dedicated `rpi-setup` account. Its polkit rule permits NetworkManager profile changes, connection activation, and a protected hotspot. Per-device credentials, certificates, and network profiles stay on the Pi, outside the Git checkout. Re-run the installer after pulling updates. It retains existing credentials and restarts the service.

To stop serving the page at boot, run `sudo systemctl disable --now rpi-setup`. An already active hotspot can be stopped separately with `sudo nmcli connection down "Pi setup hotspot"` from the Pi's console.

## Field check

1. Install while connected to home Wi-Fi. From a second device on the same LAN, sign in and check the reported address.
2. With Ethernet unplugged, power the Pi up out of range of saved networks. Join its hotspot and load the page.
3. Try a wrong Wi-Fi password. After the join attempt times out, reconnect to the hotspot.
4. Submit a valid Wi-Fi network and reconnect your client to that LAN. Reboot the Pi and confirm the page returns on the saved network.

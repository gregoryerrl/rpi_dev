# Portable SSH access on Raspberry Pi 5

On a known Wi-Fi network, SSH to the Pi at its LAN address. If NetworkManager has no active Wi-Fi or Ethernet connection for about a minute, the Pi creates an **open** hotspot named `Pi-Setup-<hostname>`. Join it and SSH to `10.42.0.1` with the Pi's normal SSH credentials. Wi-Fi association requires no password. Nearby clients can reach any service bound to that interface.

## Install or upgrade

On a Pi with NetworkManager managing `wlan0`, run:

```sh
cd ~/rpi_dev/raspberry-pi-5
sudo ./install.sh
```

The installer enables OpenSSH and the fallback monitor at boot. Upgrades replace the configuration web service and convert its saved hotspot to open Wi-Fi. If the old protected hotspot is active during the update, the change applies the next time the hotspot starts. If your laptop remembers the old password, forget the saved hotspot and join again. Package prerequisites on Debian Trixie are `network-manager`, `dnsmasq-base`, `openssh-server`, `python3-dbus` and `polkitd`.

## Move between networks

1. On the hotspot, connect with `ssh <pi-user>@10.42.0.1`.
2. Run `nmcli -f NAME,TYPE connection show` to see saved profiles. To return home, run `sudo pi-wifi-return 'netplan-wlan0-archer_2.4G'`, substituting your saved home profile on other Pis. The switch runs as a system job and finishes after the hotspot SSH connection drops.
3. Join the home network on your laptop and start a new SSH connection to the Pi's LAN IP or its mDNS hostname if available. On the original Pi this is `ssh stryka@192.168.0.117`; DHCP may assign another address later. If the switch fails and the Pi stays offline, the hotspot returns after about a minute.

To add another Wi-Fi profile over SSH, use NetworkManager's `nmtui` connection editor to save its settings, then give its profile name to `pi-wifi-return`. At boot, NetworkManager tries saved Wi-Fi first. The fallback hotspot remains available until you request a handoff or Ethernet connects.

## Check status

```sh
nmcli device status
ip -br -4 address
systemctl status rpi-setup ssh
journalctl -u rpi-wifi-return -b
```

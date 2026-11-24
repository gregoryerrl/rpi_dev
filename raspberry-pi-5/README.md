# Portable SSH access on Raspberry Pi 5

On a known Wi-Fi network, SSH to the Pi at its LAN address. If NetworkManager has no active Wi-Fi or Ethernet connection for about a minute, the Pi creates an **open** hotspot named `Pi-Setup-<hostname>`. Join it and SSH to `10.42.0.1` with the Pi's normal SSH credentials. Wi-Fi association requires no password. Nearby clients can reach any service bound to that interface.

## Install or upgrade

On a Pi with NetworkManager managing `wlan0`, run:

```sh
# From the root of your cloned repository
sudo apt install network-manager dnsmasq-base openssh-server python3-dbus polkitd
cd raspberry-pi-5
sudo ./install.sh
```

The installer enables OpenSSH and the fallback monitor at boot. Upgrades replace the configuration web service and convert its saved hotspot to open Wi-Fi. If the old protected hotspot is active during the update, the change applies the next time the hotspot starts. If your laptop remembers the old password, forget the saved hotspot and join again. Package prerequisites on Debian Trixie are `network-manager`, `dnsmasq-base`, `openssh-server`, `python3-dbus` and `polkitd`.

## Move between networks

1. Join `Pi-Setup-<hostname>` on your laptop and SSH to `<pi-user>@10.42.0.1`.
2. Run `pi-wifi`. Choose a network by number or press **a** to enter an SSID, including a hidden one. Browsing the list is read-only. When you confirm a switch the menu uses `sudo`. For a new personal network it also prompts privately for the Wi-Fi password.
3. Join the selected network on your laptop and reconnect with `ssh <pi-user>@<pi-hostname>.local`, or use the Pi's new IP from the router. A system job completes the switch after SSH disconnects. If the join fails, it tries to restore the previous connection. On the fallback hotspot, reconnect at `10.42.0.1`.

Press **r** to refresh nearby networks. If the Pi’s single radio needs to pause the hotspot, the menu asks first. After the hotspot returns, reconnect over SSH and run `pi-wifi` again. Results from that scan are available for five minutes. You can also run `pi-wifi --list` for a quick look without prompting or scanning.

Saved profiles can include enterprise Wi-Fi. To add an enterprise profile, configure it with `sudo nmtui-edit`, then select it in `pi-wifi`. New personal networks are saved for future boots after the first successful join. For scripts, `pi-wifi --profile 'YOUR SAVED PROFILE'` and the existing `sudo pi-wifi-return 'YOUR SAVED PROFILE'` select a saved connection by its NetworkManager profile name.

NetworkManager wakes the fallback service when a connection goes up or down. On a stable LAN, systemd normally reports `active (exited)`; the next link change runs the check again.

## Check status

```sh
nmcli device status
ip -br -4 address
systemctl status rpi-setup ssh
journalctl -u rpi-wifi-return -b
```

## Verify a deployment

Run `/usr/bin/python3 -m unittest -v` from this directory. On the Pi, check `systemctl is-enabled ssh rpi-setup`, then open a second SSH connection to the LAN address. Verify the hotspot and the return to a saved profile once per new hardware setup, with a local console or Ethernet available if recovery is needed. The model profile assumes the built-in Wi-Fi interface is named `wlan0`.

Re-running the installer updates the service and preserves the device's hotspot UUID and saved networks. To disable fallback while keeping SSH, run `sudo systemctl disable --now rpi-setup.service`. If already on the hotspot, return to the LAN before taking it down.

# Raspberry Pi device templates

Use **Use this template → Create a new repository** on GitHub to give a device project its own settings and history. To deploy the defaults, clone this repository directly. Install from the appropriate model directory.

| Tested device | Operating system | Setup |
| --- | --- | --- |
| Raspberry Pi 5 Model B | Raspberry Pi OS / Debian Trixie userspace, 64-bit, NetworkManager | [Portable SSH with an open fallback hotspot](raspberry-pi-5/README.md) |

After connecting over SSH, run `pi-wifi` to see nearby and saved networks or switch the Pi to another network. [Wi-Fi menu instructions](raspberry-pi-5/README.md#move-between-networks)

For a headless installation, configure a unique hostname, user, SSH key or password, Wi-Fi country, and home network in Raspberry Pi Imager. Boot and SSH into the Pi before running the model installer. Each install generates its own hotspot profile on the device. Keep Wi-Fi credentials, SSH keys, and generated machine settings out of the repository.

To improve the template, edit the model directory, run its checks, and test the change on a Pi before updating existing devices. A repository created from a template is an independent copy. [Raspberry Pi Imager setup](https://www.raspberrypi.com/documentation/computers/getting-started.html) · [GitHub template behavior](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
